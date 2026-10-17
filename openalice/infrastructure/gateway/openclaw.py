import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from openalice.application.ports import AssistantError, AssistantGateway
from openalice.logging import LogType, get_logger

logger = get_logger("openalice.openclaw")


class OpenClawError(AssistantError):
    pass


class RetryStrategy(Protocol):
    @property
    def max_attempts(self) -> int: ...

    def should_retry_status(self, status: int) -> bool: ...

    def delay_seconds(self, attempt: int) -> float: ...


@dataclass(frozen=True, slots=True)
class ExponentialBackoffRetry:
    max_attempts: int = 8
    retryable_statuses: frozenset[int] = frozenset({502, 503, 504})
    initial_delay_seconds: float = 0.5
    maximum_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("Retry policy requires at least one attempt")
        if self.initial_delay_seconds < 0 or self.maximum_delay_seconds < 0:
            raise ValueError("Retry delays must not be negative")

    def should_retry_status(self, status: int) -> bool:
        return status in self.retryable_statuses

    def delay_seconds(self, attempt: int) -> float:
        return float(min(self.initial_delay_seconds * (2**attempt), self.maximum_delay_seconds))


AssistantClient = AssistantGateway


class FakeOpenClawClient:
    """Local, side-effect-free replacement used for moderation and tests."""

    def __init__(self, response: str, delay_seconds: float = 0.0) -> None:
        self._response = response
        self._delay_seconds = delay_seconds

    async def close(self) -> None:
        return None

    async def ask(self, message: str, user: str) -> str:
        logger.info(
            LogType.TECH,
            "stage=fake_gateway status=requesting input_chars=%d delay_seconds=%.1f",
            len(message),
            self._delay_seconds,
        )
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        logger.info(
            LogType.TECH, "stage=fake_gateway status=response answer_chars=%d", len(self._response)
        )
        return self._response


class OpenClawClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        agent: str,
        timeout_seconds: float = 300.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_strategy: RetryStrategy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._agent = agent
        self._retry = retry_strategy or ExponentialBackoffRetry()
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            transport=transport,
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
        for attempt in range(self._retry.max_attempts):
            logger.info(
                LogType.TECH,
                "stage=gateway status=requesting attempt=%d model=%s input_chars=%d",
                attempt + 1,
                self._agent,
                len(message),
            )
            try:
                response = await self._client.post("/v1/responses", json=payload)
                response.raise_for_status()
                logger.info(
                    LogType.TECH,
                    "stage=gateway status=response attempt=%d http_status=%d elapsed_ms=%.1f",
                    attempt + 1,
                    response.status_code,
                    (time.perf_counter() - started) * 1000,
                )
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if (
                    self._retry.should_retry_status(status)
                    and attempt < self._retry.max_attempts - 1
                ):
                    retry_delay = self._retry.delay_seconds(attempt)
                    logger.warning(
                        LogType.TECH,
                        "stage=gateway status=retrying attempt=%d http_status=%d delay_seconds=%.1f",
                        attempt + 1,
                        status,
                        retry_delay,
                    )
                    await self._sleep(retry_delay)
                    continue
                detail = _response_error_detail(exc.response)
                raise OpenClawError(
                    f"OpenClaw request failed with HTTP {status}: {detail}"
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self._retry.max_attempts - 1:
                    retry_delay = self._retry.delay_seconds(attempt)
                    logger.warning(
                        LogType.TECH,
                        "stage=gateway status=retrying attempt=%d error=%s delay_seconds=%.1f",
                        attempt + 1,
                        type(exc).__name__,
                        retry_delay,
                    )
                    await self._sleep(retry_delay)
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
