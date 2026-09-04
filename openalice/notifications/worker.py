import asyncio

from openalice.logging import LogType, get_logger
from openalice.notifications.notifiers import Notifier
from openalice.store import Store

logger = get_logger("openalice.notifications")


class NotificationWorker:
    def __init__(
            self,
            store: Store,
            notifier: Notifier,
            max_attempts: int,
            poll_seconds: float,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._max_attempts = max_attempts
        self._poll_seconds = poll_seconds
        self._wake_event = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def wake(self) -> None:
        self._wake_event.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake_event.set()
        if self._task is not None:
            await self._task
        await self._notifier.close()

    async def _run(self) -> None:
        while not self._stopping:
            await self._deliver_pending()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass
            self._wake_event.clear()

    async def _deliver_pending(self) -> None:
        for notification in await self._store.get_pending_notifications():
            if self._stopping:
                return
            try:
                await self._notifier.notify(notification)
            except Exception as exc:
                attempt = notification.attempts + 1
                exhausted = attempt >= self._max_attempts
                retry_delay = min(2 ** attempt, 60)
                await self._store.mark_notification_failed(
                    notification.event_id,
                    attempt,
                    type(exc).__name__,
                    retry_delay,
                    exhausted,
                )
                logger.warning(
                    LogType.TECH,
                    "stage=notification status=%s event=%s channel=%s attempt=%d error_type=%s",
                    "failed" if exhausted else "retrying",
                    notification.event_id[:12],
                    notification.channel,
                    attempt,
                    type(exc).__name__,
                )
            else:
                await self._store.mark_notification_delivered(notification.event_id)
                logger.info(
                    LogType.TECH,
                    "stage=notification status=delivered event=%s channel=%s",
                    notification.event_id[:12],
                    notification.channel,
                )
                logger.info(
                    LogType.USER,
                    "event=ready_notification_delivered channel=%s",
                    notification.channel,
                )
