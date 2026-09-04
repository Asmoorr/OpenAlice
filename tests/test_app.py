import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from openalice.app import create_app
from openalice.config import Settings
from openalice.notifications.models import Notification


DEFAULT_PENDING_PHRASES = {
    "Мне нужно немного времени. Скажите «готово» через несколько секунд.",
    "Ответ ещё готовится. Скажите «готово» немного позже.",
}


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
    return Settings(**values)


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


def test_health(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path / "test.db"), FakeOpenClaw())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mode"] == "live"


def test_fake_mode_uses_local_response_without_injected_gateway(tmp_path: Path) -> None:
    app = create_app(
        settings(
            tmp_path / "test.db",
            openalice_fake_mode=True,
            openalice_fake_response="Безопасный тестовый ответ",
        )
    )

    with TestClient(app) as client:
        health = client.get("/health")
        response = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Включи устройство"),
        )

    assert health.json()["mode"] == "fake"
    assert response.json()["response"]["text"] == "Безопасный тестовый ответ"


def test_fake_mode_can_simulate_deferred_response(tmp_path: Path) -> None:
    app = create_app(
        settings(
            tmp_path / "test.db",
            openalice_fake_mode=True,
            openalice_fake_response="Отложенный тестовый ответ",
            openalice_fake_delay_seconds=0.2,
            alice_fast_timeout_seconds=0.11,
        )
    )

    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгая тестовая команда"),
        )
        time.sleep(0.25)
        result = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=2),
        )

    assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES
    assert result.json()["response"]["text"] == "Отложенный тестовый ответ"


def test_fast_openclaw_response_and_deduplication(tmp_path: Path) -> None:
    fake = FakeOpenClaw(answer="**Короткий** [ответ](https://example.com)")
    app = create_app(settings(tmp_path / "test.db"), fake)
    with TestClient(app) as client:
        first = client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Вопрос"))
        duplicate = client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Вопрос"))

    assert first.status_code == 200
    assert first.json()["response"]["text"] == "Короткий ответ"
    assert duplicate.json() == first.json()
    assert len(fake.calls) == 1


def test_deferred_response(tmp_path: Path) -> None:
    fake = FakeOpenClaw(answer="Отложенный ответ", delay=0.3)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        fake,
    )
    with TestClient(app) as client:
        pending = client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Долгий вопрос"))
        assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES
        time.sleep(0.35)
        result = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=2),
        )

    assert result.json()["response"]["text"] == "Отложенный ответ"


def test_deferred_response_uses_configured_pending_phrase(tmp_path: Path) -> None:
    fake = FakeOpenClaw(answer="Отложенный ответ", delay=0.3)
    app = create_app(
        settings(
            tmp_path / "test.db",
            alice_fast_timeout_seconds=0.11,
            alice_pending_phrases="Пожалуйста, подождите и скажите «готово».",
        ),
        fake,
    )

    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгий вопрос"),
        )
        still_pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=2),
        )

    assert pending.json()["response"]["text"] == "Пожалуйста, подождите и скажите «готово»."
    assert still_pending.json()["response"]["text"] == "Пожалуйста, подождите и скажите «готово»."


def test_deferred_response_announces_when_ready(tmp_path: Path) -> None:
    fake_openclaw = FakeOpenClaw(answer="Отложенный ответ", delay=0.2)
    fake_notifier = FakeNotifier()
    app = create_app(
        settings(
            tmp_path / "test.db",
            alice_fast_timeout_seconds=0.11,
            notifications_enabled=True,
            home_assistant_token="home-assistant-token",
            home_assistant_entity_id="media_player.yandex_station_mini",
            notification_ready_phrase="Ответ подготовлен.",
            notification_poll_seconds=0.1,
        ),
        fake_openclaw,
        fake_notifier,
    )

    with TestClient(app) as client:
        client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгий вопрос"),
        )
        time.sleep(0.25)
        result = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=2),
        )

    assert len(fake_notifier.notifications) == 1
    assert fake_notifier.notifications[0].target == "media_player.yandex_station_mini"
    assert fake_notifier.notifications[0].text == "Ответ подготовлен."
    assert result.json()["response"]["text"] == "Отложенный ответ"


def test_allowlist_and_wrong_secret(tmp_path: Path) -> None:
    fake = FakeOpenClaw()
    app = create_app(
        settings(tmp_path / "test.db", alice_allowed_user_ids=frozenset({"another-user"})),
        fake,
    )
    with TestClient(app) as client:
        denied = client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Вопрос"))
        missing = client.post("/alice/webhook/wrong", json=alice_request("Вопрос", message_id=2))

    assert denied.json()["response"]["end_session"] is True
    assert missing.status_code == 404
    assert fake.calls == []


def test_new_dialog_changes_openclaw_session(tmp_path: Path) -> None:
    fake = FakeOpenClaw()
    app = create_app(settings(tmp_path / "test.db"), fake)
    with TestClient(app) as client:
        client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Первый вопрос"))
        client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("новый диалог", message_id=2))
        client.post("/alice/webhook/a-very-long-test-secret", json=alice_request("Второй вопрос", message_id=3))

    assert fake.calls[0][1].endswith(":v0")
    assert fake.calls[1][1].endswith(":v1")
