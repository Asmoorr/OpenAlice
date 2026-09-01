from typing import Any

import httpx


class OpenClawError(RuntimeError):
    pass


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
        payload = {
            "model": self._agent,
            "input": message,
            "user": user,
            "instructions": (
                "Отвечай по-русски, пригодным для озвучивания текстом без Markdown. "
                "Сначала дай краткий полезный ответ, желательно до 800 символов."
            ),
        }
        try:
            response = await self._client.post("/v1/responses", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenClawError(f"OpenClaw request failed: {exc}") from exc

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

