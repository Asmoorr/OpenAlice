import asyncio
from pathlib import Path

from openalice.config import Settings
from openalice.domain.models import Notification


class FakeOpenClaw:
    def __init__(self, answer: str = "Готовый ответ", delay: float = 0) -> None:
        self.answer = answer
        self.delay = delay
        self.calls: list[tuple[str, str]] = []

    async def ask(self, message: str, user: str) -> str:
        self.calls.append((message, user))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.answer

    async def close(self) -> None:
        return None


class FakeNotifier:
    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    async def notify(self, notification: Notification) -> None:
        self.notifications.append(notification)

    async def close(self) -> None:
        return None


def settings(database_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "openclaw_gateway_token": "test-token",
        "alice_webhook_secret": "a-very-long-test-secret",
        "alice_fast_timeout_seconds": 0.2,
        "database_path": database_path,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def alice_request(command: str, message_id: int = 1, new: bool = False) -> dict[str, object]:
    return {
        "request": {
            "command": command,
            "original_utterance": command,
            "type": "SimpleUtterance",
        },
        "session": {
            "message_id": message_id,
            "session_id": "alice-session",
            "skill_id": "alice-skill",
            "new": new,
            "application": {"application_id": "application-1"},
            "user": {"user_id": "user-1"},
        },
        "version": "1.0",
    }
