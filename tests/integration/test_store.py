import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from openalice.domain.models import Job, JobStatus, Notification
from openalice.infrastructure.persistence import SqliteStore


async def test_reads_database_created_by_legacy_store(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                conversation_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                response TEXT,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO jobs(conversation_id, status, response) VALUES (?, 'done', ?)",
            ("conversation-1", "Сохранённый ответ"),
        )

    store = SqliteStore(path)
    await store.initialize()

    assert await store.get_job("conversation-1") == Job(
        JobStatus.DONE,
        response="Сохранённый ответ",
    )


async def test_completed_job_and_notification_are_atomic(tmp_path: Path) -> None:
    path = tmp_path / "atomic.db"
    store = SqliteStore(path)
    await store.initialize()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TRIGGER reject_notification
            BEFORE INSERT ON notification_deliveries
            BEGIN
              SELECT RAISE(ABORT, 'controlled notification failure');
            END
            """
        )
    notification = Notification(
        "event-1",
        "conversation-1",
        "answer_ready",
        "home_assistant",
        "media_player.station",
        "Ответ готов.",
    )

    with pytest.raises(sqlite3.IntegrityError, match="controlled notification failure"):
        await store.complete_with_notification(
            "conversation-1",
            "Полный ответ",
            notification,
        )

    assert await store.get_job("conversation-1") is None
    assert await store.get_pending_notifications() == []


async def test_repository_operations_and_concurrent_generation(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "repository.db")
    await store.initialize()
    await store.set_job("conversation-1", Job.pending())
    await store.cache_response("request-1", {"response": {"text": "Ответ"}})

    generations = await asyncio.gather(*(store.increment_generation("identity") for _ in range(10)))

    assert await store.get_job("conversation-1") == Job.pending()
    assert await store.get_cached_response("request-1") == {"response": {"text": "Ответ"}}
    assert sorted(generations) == list(range(1, 11))
    assert await store.get_generation("identity") == 10

    await store.delete_job("conversation-1")
    assert await store.get_job("conversation-1") is None


async def test_initialize_recovers_pending_jobs_and_removes_expired_rows(tmp_path: Path) -> None:
    path = tmp_path / "cleanup.db"
    store = SqliteStore(path)
    await store.initialize()
    await store.set_job("pending-conversation", Job.pending())
    await store.cache_response("expired-request", {"response": {"text": "old"}})
    notification = Notification(
        "old-event",
        "completed-conversation",
        "answer_ready",
        "home_assistant",
        "media_player.station",
        "Ответ готов.",
    )
    await store.complete_with_notification(
        "completed-conversation",
        "Ответ",
        notification,
    )
    await store.mark_notification_delivered(notification.event_id)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE request_cache SET created_at = datetime('now', '-8 days')")
        connection.execute(
            "UPDATE notification_deliveries SET created_at = datetime('now', '-8 days')"
        )

    await store.initialize()

    recovered = await store.get_job("pending-conversation")
    assert recovered == Job(JobStatus.FAILED, error="Приложение было перезапущено.")
    assert await store.get_cached_response("expired-request") is None
    with closing(sqlite3.connect(path)) as connection, connection:
        count = connection.execute("SELECT COUNT(*) FROM notification_deliveries").fetchone()[0]
    assert count == 0


async def test_notification_retry_state_and_exhaustion(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "notifications.db")
    await store.initialize()
    notification = Notification(
        "event-1",
        "conversation-1",
        "answer_ready",
        "home_assistant",
        "media_player.station",
        "Ответ готов.",
    )
    await store.complete_with_notification("conversation-1", "Ответ", notification)

    await store.mark_notification_failed("event-1", 1, "temporary", 0, False)
    pending = await store.get_pending_notifications()
    assert len(pending) == 1
    assert pending[0].attempts == 1

    await store.mark_notification_failed("event-1", 2, "permanent", 0, True)
    assert await store.get_pending_notifications() == []
