import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from openalice.notifications.models import Notification


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        await self._execute_script(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
                conversation_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                response TEXT,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS request_cache (
                request_key TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS generations (
                identity_hash TEXT PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                event_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                channel TEXT NOT NULL,
                target TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                delivered_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notification_deliveries_pending
              ON notification_deliveries(status, next_attempt_at);
            UPDATE jobs SET status = 'failed', error = 'Приложение было перезапущено.'
              WHERE status = 'pending';
            DELETE FROM request_cache WHERE created_at < datetime('now', '-7 days');
            DELETE FROM notification_deliveries
             WHERE status != 'pending'
               AND created_at < datetime('now', '-7 days');
            """
        )

    async def set_job(self, conversation_id: str, status: str, response: str | None = None,
                      error: str | None = None) -> None:
        await self._execute(
            """
            INSERT INTO jobs(conversation_id, status, response, error, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(conversation_id) DO UPDATE SET
              status=excluded.status, response=excluded.response,
              error=excluded.error, updated_at=CURRENT_TIMESTAMP
            """,
            (conversation_id, status, response, error),
        )

    async def get_job(self, conversation_id: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT status, response, error FROM jobs WHERE conversation_id = ?",
            (conversation_id,),
        )
        if row is None:
            return None
        return {"status": row[0], "response": row[1], "error": row[2]}

    async def delete_job(self, conversation_id: str) -> None:
        await self._execute_transaction(
            (
                (
                    "UPDATE notification_deliveries SET status = 'cancelled' "
                    "WHERE conversation_id = ? AND status = 'pending'",
                    (conversation_id,),
                ),
                ("DELETE FROM jobs WHERE conversation_id = ?", (conversation_id,)),
            )
        )

    async def complete_job_and_enqueue_notification(
            self,
            conversation_id: str,
            response: str,
            notification: Notification,
    ) -> None:
        await self._execute_transaction(
            (
                (
                    """
                    INSERT INTO jobs(conversation_id, status, response, error, updated_at)
                    VALUES (?, 'done', ?, NULL, CURRENT_TIMESTAMP)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                      status='done', response=excluded.response, error=NULL,
                      updated_at=CURRENT_TIMESTAMP
                    """,
                    (conversation_id, response),
                ),
                (
                    """
                    INSERT INTO notification_deliveries(
                      event_id, conversation_id, kind, channel, target, text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notification.event_id,
                        conversation_id,
                        notification.kind,
                        notification.channel,
                        notification.target,
                        notification.text,
                    ),
                ),
            )
        )

    async def get_pending_notifications(self, limit: int = 20) -> list[Notification]:
        rows = await self._fetchall(
            """
            SELECT n.event_id, n.conversation_id, n.kind, n.channel,
                   n.target, n.text, n.attempts
              FROM notification_deliveries AS n
              JOIN jobs AS j ON j.conversation_id = n.conversation_id
             WHERE n.status = 'pending'
               AND n.next_attempt_at <= CURRENT_TIMESTAMP
               AND j.status = 'done'
             ORDER BY n.created_at
             LIMIT ?
            """,
            (limit,),
        )
        return [Notification(*row) for row in rows]

    async def mark_notification_delivered(self, event_id: str) -> None:
        await self._execute(
            """
            UPDATE notification_deliveries
               SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP
             WHERE event_id = ? AND status = 'pending'
            """,
            (event_id,),
        )

    async def mark_notification_failed(
            self,
            event_id: str,
            attempts: int,
            error: str,
            retry_delay_seconds: int,
            exhausted: bool,
    ) -> None:
        await self._execute(
            """
            UPDATE notification_deliveries
               SET status = ?, attempts = ?, last_error = ?,
                   next_attempt_at = datetime('now', ?)
             WHERE event_id = ? AND status = 'pending'
            """,
            (
                "failed" if exhausted else "pending",
                attempts,
                error[:200],
                f"+{retry_delay_seconds} seconds",
                event_id,
            ),
        )

    async def get_cached_response(self, request_key: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT response_json FROM request_cache WHERE request_key = ?",
            (request_key,),
        )
        return json.loads(row[0]) if row else None

    async def cache_response(self, request_key: str, response: dict[str, Any]) -> None:
        await self._execute(
            "INSERT OR REPLACE INTO request_cache(request_key, response_json) VALUES (?, ?)",
            (request_key, json.dumps(response, ensure_ascii=False)),
        )

    async def get_generation(self, identity_hash: str) -> int:
        row = await self._fetchone(
            "SELECT generation FROM generations WHERE identity_hash = ?",
            (identity_hash,),
        )
        return int(row[0]) if row else 0

    async def increment_generation(self, identity_hash: str) -> int:
        await self._execute(
            """
            INSERT INTO generations(identity_hash, generation) VALUES (?, 1)
            ON CONFLICT(identity_hash) DO UPDATE SET generation = generation + 1
            """,
            (identity_hash,),
        )
        return await self.get_generation(identity_hash)

    async def _execute_script(self, script: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._execute_script_sync, script)

    def _execute_script_sync(self, script: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.executescript(script)

    async def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._execute_sync, sql, params)

    def _execute_sync(self, sql: str, params: tuple[Any, ...]) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(sql, params)

    async def _execute_transaction(
            self,
            statements: tuple[tuple[str, tuple[Any, ...]], ...],
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(self._execute_transaction_sync, statements)

    def _execute_transaction_sync(
            self,
            statements: tuple[tuple[str, tuple[Any, ...]], ...],
    ) -> None:
        with sqlite3.connect(self._path) as connection:
            for sql, params in statements:
                connection.execute(sql, params)

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        async with self._lock:
            return await asyncio.to_thread(self._fetchone_sync, sql, params)

    def _fetchone_sync(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with sqlite3.connect(self._path) as connection:
            cursor = connection.execute(sql, params)
            return cursor.fetchone()

    async def _fetchall(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        async with self._lock:
            return await asyncio.to_thread(self._fetchall_sync, sql, params)

    def _fetchall_sync(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self._path) as connection:
            cursor = connection.execute(sql, params)
            return cursor.fetchall()
