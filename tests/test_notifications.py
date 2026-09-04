import asyncio
from pathlib import Path

import httpx

from openalice.notifications.models import Notification
from openalice.notifications.notifiers import HomeAssistantNotifier
from openalice.notifications.worker import NotificationWorker
from openalice.store import Store


def notification(event_id: str = "event-1") -> Notification:
    return Notification(
        event_id=event_id,
        conversation_id="conversation-1",
        kind="answer_ready",
        channel="home_assistant",
        target="media_player.yandex_station_mini",
        text="Ответ готов.",
    )


async def test_home_assistant_notifier_sends_tts_payload() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json=[])

    notifier = HomeAssistantNotifier(
        "http://home-assistant.local:8123",
        "secret-token",
        3.0,
        transport=httpx.MockTransport(handler),
    )
    await notifier.notify(notification())
    await notifier.close()

    assert captured is not None
    assert captured.url.path == "/api/services/media_player/play_media"
    assert captured.headers["Authorization"] == "Bearer secret-token"
    assert captured.read().decode() == (
        '{"entity_id":"media_player.yandex_station_mini",'
        '"media_content_type":"text","media_content_id":"Ответ готов."}'
    )


class RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    async def notify(self, item: Notification) -> None:
        self.notifications.append(item)

    async def close(self) -> None:
        return None


class FailingNotifier:
    async def notify(self, item: Notification) -> None:
        raise httpx.ConnectError("Home Assistant is unavailable")

    async def close(self) -> None:
        return None


async def test_worker_delivers_persisted_notification(tmp_path: Path) -> None:
    store = Store(tmp_path / "notifications.db")
    await store.initialize()
    item = notification()
    await store.complete_job_and_enqueue_notification(
        item.conversation_id,
        "Полный ответ",
        item,
    )
    notifier = RecordingNotifier()
    worker = NotificationWorker(store, notifier, max_attempts=3, poll_seconds=0.01)

    worker.start()
    worker.wake()
    for _ in range(20):
        if notifier.notifications:
            break
        await asyncio.sleep(0.01)
    await worker.stop()

    assert notifier.notifications == [item]
    assert await store.get_pending_notifications() == []


async def test_consumed_job_cancels_pending_notification(tmp_path: Path) -> None:
    store = Store(tmp_path / "notifications.db")
    await store.initialize()
    item = notification()
    await store.complete_job_and_enqueue_notification(
        item.conversation_id,
        "Полный ответ",
        item,
    )

    await store.delete_job(item.conversation_id)

    assert await store.get_pending_notifications() == []


async def test_notification_failure_does_not_remove_ready_answer(tmp_path: Path) -> None:
    store = Store(tmp_path / "notifications.db")
    await store.initialize()
    item = notification()
    await store.complete_job_and_enqueue_notification(
        item.conversation_id,
        "Полный ответ",
        item,
    )
    worker = NotificationWorker(store, FailingNotifier(), max_attempts=1, poll_seconds=0.01)

    worker.start()
    worker.wake()
    await asyncio.sleep(0.05)
    await worker.stop()

    job = await store.get_job(item.conversation_id)
    assert job is not None
    assert job["status"] == "done"
    assert job["response"] == "Полный ответ"
    assert await store.get_pending_notifications() == []
