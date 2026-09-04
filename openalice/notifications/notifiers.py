from typing import Protocol

import httpx

from openalice.notifications.models import Notification


class Notifier(Protocol):
    async def notify(self, notification: Notification) -> None: ...

    async def close(self) -> None: ...


class NoOpNotifier:
    async def notify(self, notification: Notification) -> None:
        return None

    async def close(self) -> None:
        return None


class HomeAssistantNotifier:
    def __init__(
            self,
            base_url: str,
            token: str,
            timeout_seconds: float,
            transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def notify(self, notification: Notification) -> None:
        response = await self._client.post(
            "/api/services/media_player/play_media",
            json={
                "entity_id": notification.target,
                "media_content_type": "text",
                "media_content_id": notification.text,
            },
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
