from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


class RequestCoordinator:
    """Owns process-local request tasks and keyed conversation locks."""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task[object]] = {}
        self._pending: dict[str, asyncio.Task[str]] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._locks: dict[str, _LockEntry] = {}
        self._closed = False

    @property
    def registry_sizes(self) -> tuple[int, int, int, int]:
        return (
            len(self._inflight),
            len(self._pending),
            len(self._background),
            len(self._locks),
        )

    async def run_once(self, key: str, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        self._ensure_open()
        existing = self._inflight.get(key)
        if existing is None:
            task: asyncio.Task[T] = asyncio.create_task(operation())
            self._inflight[key] = task
            task.add_done_callback(lambda completed: self._release_inflight(key, completed))
        else:
            task = existing  # type: ignore[assignment]
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        self._ensure_open()
        entry = self._locks.setdefault(key, _LockEntry(asyncio.Lock()))
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0 and not entry.lock.locked():
                self._locks.pop(key, None)

    def start_pending(self, key: str, awaitable: Coroutine[Any, Any, str]) -> asyncio.Task[str]:
        self._ensure_open()
        task = asyncio.create_task(awaitable)
        self._pending[key] = task
        return task

    def is_current_pending(self, key: str, task: asyncio.Task[str]) -> bool:
        return self._pending.get(key) is task

    def pop_pending(
        self, key: str, task: asyncio.Task[str] | None = None
    ) -> asyncio.Task[str] | None:
        current = self._pending.get(key)
        if current is None or (task is not None and current is not task):
            return None
        return self._pending.pop(key)

    def cancel_pending(self, key: str) -> bool:
        task = self._pending.pop(key, None)
        if task is None:
            return False
        if not task.done():
            task.cancel()
        return True

    def track_background(self, awaitable: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        self._ensure_open()
        task = asyncio.create_task(awaitable)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = {
            *self._inflight.values(),
            *self._pending.values(),
            *self._background,
        }
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._pending.clear()
        self._background.clear()
        self._locks.clear()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Request coordinator is closed")

    def _release_inflight(self, key: str, task: asyncio.Task[object]) -> None:
        if self._inflight.get(key) is task:
            self._inflight.pop(key, None)
        if not task.cancelled():
            task.exception()
