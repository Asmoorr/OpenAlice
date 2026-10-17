import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from openalice.app import create_app
from openalice.infrastructure.gateway import OpenClawError
from tests.support import FakeNotifier, FakeOpenClaw, alice_request, settings

DEFAULT_PENDING_PHRASES = {
    "Мне нужно немного времени. Скажите «готово» через несколько секунд.",
    "Ответ ещё готовится. Скажите «готово» немного позже.",
}


class FailingOpenClaw:
    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.closed = False

    async def ask(self, message: str, user: str) -> str:
        del message, user
        if self.delay:
            await asyncio.sleep(self.delay)
        raise OpenClawError("controlled gateway failure")

    async def close(self) -> None:
        self.closed = True


class BlockingOpenClaw:
    def __init__(self) -> None:
        self.cancelled = False
        self.closed = False

    async def ask(self, message: str, user: str) -> str:
        del message, user
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def close(self) -> None:
        self.closed = True


class ControlledOpenClaw:
    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.release = Event()

    async def ask(self, message: str, user: str) -> str:
        del message, user
        await asyncio.to_thread(self.release.wait)
        if self.answer is None:
            raise OpenClawError("controlled deferred failure")
        return self.answer

    async def close(self) -> None:
        self.release.set()


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
        duplicate = client.post(
            "/alice/webhook/a-very-long-test-secret", json=alice_request("Вопрос")
        )

    assert first.status_code == 200
    assert first.json()["response"]["text"] == "Короткий ответ"
    assert duplicate.json() == first.json()
    assert len(fake.calls) == 1


def test_concurrent_duplicate_webhooks_share_one_request(tmp_path: Path) -> None:
    fake = FakeOpenClaw(delay=0.1)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.5),
        fake,
    )
    barrier = Barrier(2)

    with TestClient(app) as client:

        def send() -> dict[str, object]:
            barrier.wait()
            return client.post(
                "/alice/webhook/a-very-long-test-secret",
                json=alice_request("Одинаковый вопрос"),
            ).json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send(), range(2)))

    assert responses[0] == responses[1]
    assert len(fake.calls) == 1


def test_concurrent_messages_for_one_user_start_only_one_openclaw_request(tmp_path: Path) -> None:
    fake = FakeOpenClaw(delay=0.3)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        fake,
    )
    barrier = Barrier(2)

    with TestClient(app) as client:

        def send(message_id: int) -> dict[str, object]:
            barrier.wait()
            return client.post(
                "/alice/webhook/a-very-long-test-secret",
                json=alice_request(f"Вопрос {message_id}", message_id=message_id),
            ).json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, (1, 2)))

    assert all(response["response"]["text"] in DEFAULT_PENDING_PHRASES for response in responses)
    assert len(fake.calls) == 1


def test_deferred_response(tmp_path: Path) -> None:
    fake = FakeOpenClaw(answer="Отложенный ответ", delay=0.3)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        fake,
    )
    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret", json=alice_request("Долгий вопрос")
        )
        assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES
        time.sleep(0.35)
        result = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=2),
        )

    assert result.json()["response"]["text"] == "Отложенный ответ"


def test_cancelled_deferred_request_does_not_reappear(tmp_path: Path) -> None:
    fake = FakeOpenClaw(delay=0.3)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        fake,
    )

    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгий вопрос"),
        )
        cancelled = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("отмена", message_id=2),
        )
        time.sleep(0.05)
        result = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=3),
        )

    assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES
    assert cancelled.json()["response"]["text"] == "Запрос отменён."
    assert result.json()["response"]["text"] == "Нет ожидающего ответа. Задайте новый вопрос."


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


def test_deferred_response_uses_glagol_channel(tmp_path: Path) -> None:
    fake_openclaw = FakeOpenClaw(answer="Отложенный ответ", delay=0.2)
    fake_notifier = FakeNotifier()
    app = create_app(
        settings(
            tmp_path / "test.db",
            alice_fast_timeout_seconds=0.11,
            notifications_enabled=True,
            notification_provider="glagol",
            glagol_device_id="device-1",
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

    assert len(fake_notifier.notifications) == 1
    assert fake_notifier.notifications[0].channel == "glagol"
    assert fake_notifier.notifications[0].target == "device-1"


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
        client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("новый диалог", message_id=2),
        )
        client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Второй вопрос", message_id=3),
        )

    assert fake.calls[0][1].endswith(":v0")
    assert fake.calls[1][1].endswith(":v1")


def test_skill_open_response_contract(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path / "test.db"), FakeOpenClaw())

    with TestClient(app) as client:
        response = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("", new=True),
        )

    text = (
        "Это Открытый помощник. Задайте вопрос. Если ответ готовится долго, "
        "скажите «готово» немного позже."
    )
    assert response.status_code == 200
    assert response.json() == {
        "response": {"text": text, "tts": text, "end_session": False},
        "version": "1.0",
    }


def wait_for_deferred_result(client: TestClient, expected: str) -> dict[str, object]:
    deadline = time.monotonic() + 1.0
    message_id = 2
    while time.monotonic() < deadline:
        response = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("готово", message_id=message_id),
        ).json()
        if response["response"]["text"] == expected:  # type: ignore[index]
            return response
        message_id += 1
        time.sleep(0.01)
    raise AssertionError(f"Deferred result did not become {expected!r}")


@pytest.mark.parametrize(
    ("command", "expected_text", "end_session"),
    [
        (
            "помощь",
            "Я передаю ваши вопросы домашнему помощнику OpenClaw. Можно сказать "
            "«готово», «новый диалог», «отмена» или «выйти».",
            False,
        ),
        ("готово", "Нет ожидающего ответа. Задайте новый вопрос.", False),
        ("отмена", "Сейчас нет ожидающего запроса.", False),
        ("новый диалог", "Начинаю новый диалог. О чём поговорим?", False),
        ("до свидания", "До встречи.", True),
        ("", "Я вас не расслышала. Повторите вопрос.", False),
    ],
)
def test_local_command_response_contract(
    tmp_path: Path,
    command: str,
    expected_text: str,
    end_session: bool,
) -> None:
    fake = FakeOpenClaw()
    app = create_app(settings(tmp_path / "test.db"), fake)

    with TestClient(app) as client:
        response = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request(command),
        )

    assert response.status_code == 200
    assert response.json() == {
        "response": {
            "text": expected_text,
            "tts": expected_text,
            "end_session": end_session,
        },
        "version": "1.0",
    }
    assert fake.calls == []


def test_security_response_contracts(tmp_path: Path) -> None:
    fake = FakeOpenClaw()
    app = create_app(
        settings(tmp_path / "test.db", alice_allowed_user_ids=frozenset({"allowed-user"})),
        fake,
    )

    with TestClient(app) as client:
        denied = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Секретная реплика"),
        )
        wrong_secret = client.post(
            "/alice/webhook/wrong",
            json=alice_request("Секретная реплика", message_id=2),
        )

    denied_text = "У этого аккаунта нет доступа к навыку."
    assert denied.json() == {
        "response": {"text": denied_text, "tts": denied_text, "end_session": True},
        "version": "1.0",
    }
    assert wrong_secret.status_code == 404
    assert wrong_secret.json() == {"detail": "Not found"}
    assert fake.calls == []


def test_gateway_failure_returns_stable_alice_response(tmp_path: Path) -> None:
    gateway = FailingOpenClaw()
    app = create_app(settings(tmp_path / "test.db"), gateway)

    with TestClient(app) as client:
        response = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Вопрос"),
        )

    expected = "Домашний помощник сейчас недоступен. Попробуйте ещё раз позже."
    assert response.json()["response"] == {
        "text": expected,
        "tts": expected,
        "end_session": False,
    }
    assert gateway.closed is True


def test_shutdown_cancels_pending_gateway_task(tmp_path: Path) -> None:
    gateway = BlockingOpenClaw()
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        gateway,
    )

    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгий вопрос"),
        )
        assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES

    assert gateway.cancelled is True
    assert gateway.closed is True


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Управляемый отложенный ответ", "Управляемый отложенный ответ"),
        (None, "Домашний помощник не смог подготовить ответ."),
    ],
)
def test_controlled_deferred_completion_and_failure(
    tmp_path: Path,
    answer: str | None,
    expected: str,
) -> None:
    gateway = ControlledOpenClaw(answer)
    app = create_app(
        settings(tmp_path / "test.db", alice_fast_timeout_seconds=0.11),
        gateway,
    )

    with TestClient(app) as client:
        pending = client.post(
            "/alice/webhook/a-very-long-test-secret",
            json=alice_request("Долгий вопрос"),
        )
        gateway.release.set()
        result = wait_for_deferred_result(client, expected)

    assert pending.json()["response"]["text"] in DEFAULT_PENDING_PHRASES
    assert result["response"]["text"] == expected  # type: ignore[index]


def test_logs_do_not_contain_utterance_token_or_full_identity(tmp_path: Path, caplog) -> None:
    utterance = "очень секретная пользовательская реплика"
    gateway_token = "unique-gateway-token-for-privacy-test"
    user_id = "full-private-user-identifier"
    payload = alice_request(utterance)
    payload["session"]["user"]["user_id"] = user_id  # type: ignore[index]
    app = create_app(
        settings(tmp_path / "test.db", openclaw_gateway_token=gateway_token),
        FakeOpenClaw(),
    )

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.post(
                "/alice/webhook/a-very-long-test-secret",
                json=payload,
            )

    assert response.status_code == 200
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert utterance not in rendered
    assert gateway_token not in rendered
    assert user_id not in rendered
