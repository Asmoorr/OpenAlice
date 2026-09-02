import asyncio
import logging
import time
from typing import Any, Protocol

import httpx

logger = logging.getLogger("openalice.openclaw")

_MAX_ATTEMPTS = 8
_RETRYABLE_STATUSES = {502, 503, 504}


class OpenClawError(RuntimeError):
    pass


class AssistantClient(Protocol):
    async def ask(self, message: str, user: str) -> str: ...

    async def close(self) -> None: ...


class FakeOpenClawClient:
    """Local, side-effect-free replacement used for moderation and tests."""

    def __init__(self, response: str, delay_seconds: float = 0.0) -> None:
        self._response = response
        self._delay_seconds = delay_seconds

    async def close(self) -> None:
        return None

    async def ask(self, message: str, user: str) -> str:
        logger.info(
            "stage=fake_gateway status=requesting input_chars=%d delay_seconds=%.1f",
            len(message),
            self._delay_seconds,
        )
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        logger.info(
            "stage=fake_gateway status=response answer_chars=%d", len(self._response)
        )
        return self._response


class OpenClawClient:
    def __init__(self, base_url: str, token: str, agent: str) -> None:
        self._agent = agent
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(120.0, connect=5.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ask(self, message: str, user: str) -> str:
        started = time.perf_counter()
        payload = {
            "model": self._agent,
            "input": message,
            "user": user,
            "instructions": (
                "Отвечай по-русски, пригодным для озвучивания текстом без Markdown. "
                "Сначала дай краткий полезный ответ, желательно до 800 символов."
            ),
        }
        response: httpx.Response | None = None
        for attempt in range(_MAX_ATTEMPTS):
            logger.info(
                "stage=gateway status=requesting attempt=%d model=%s input_chars=%d",
                attempt + 1,
                self._agent,
                len(message),
            )
            try:
                response = await self._client.post("/v1/responses", json=payload)
                response.raise_for_status()
                logger.info(
                    "stage=gateway status=response attempt=%d http_status=%d elapsed_ms=%.1f",
                    attempt + 1,
                    response.status_code,
                    (time.perf_counter() - started) * 1000,
                )
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in _RETRYABLE_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                    retry_delay = min(0.5 * (2**attempt), 8.0)
                    logger.warning(
                        "stage=gateway status=retrying attempt=%d http_status=%d delay_seconds=%.1f",
                        attempt + 1,
                        status,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                detail = _response_error_detail(exc.response)
                raise OpenClawError(
                    f"OpenClaw request failed with HTTP {status}: {detail}"
                ) from exc
            except httpx.RequestError as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    retry_delay = min(0.5 * (2**attempt), 8.0)
                    logger.warning(
                        "stage=gateway status=retrying attempt=%d error=%s delay_seconds=%.1f",
                        attempt + 1,
                        type(exc).__name__,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise OpenClawError(f"OpenClaw request failed: {exc}") from exc

        if response is None:  # pragma: no cover - defensive guard
            raise OpenClawError("OpenClaw request failed without a response")

        try:
            data = response.json()
        except ValueError as exc:
            raise OpenClawError("OpenClaw returned invalid JSON") from exc

        text = _extract_output_text(data)
        if not text:
            raise OpenClawError("OpenClaw returned no output text")
        return text


def _extract_output_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    output = data.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    return "\n".join(chunks)


def _response_error_detail(response: httpx.Response) -> str:
    """Return a bounded gateway error without leaking response headers or tokens."""
    body = response.text.strip().replace("\r", " ").replace("\n", " ")
    return body[:500] if body else "empty response body"
