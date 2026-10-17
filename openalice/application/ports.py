from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from openalice.domain.models import Job, Notification


class AssistantError(RuntimeError):
    """Safe application-level failure reported by an assistant adapter."""


class AssistantGateway(Protocol):
    async def ask(self, message: str, user: str) -> str: ...

    async def close(self) -> None: ...


class JobRepository(Protocol):
    async def set_job(self, conversation_id: str, job: Job) -> None: ...

    async def get_job(self, conversation_id: str) -> Job | None: ...

    async def delete_job(self, conversation_id: str) -> None: ...


class RequestCache(Protocol):
    async def get_cached_response(self, request_key: str) -> Mapping[str, Any] | None: ...

    async def cache_response(self, request_key: str, response: Mapping[str, Any]) -> None: ...


class ConversationGenerationRepository(Protocol):
    async def get_generation(self, identity_hash: str) -> int: ...

    async def increment_generation(self, identity_hash: str) -> int: ...


class DeferredCompletionRepository(Protocol):
    async def complete_with_notification(
        self,
        conversation_id: str,
        response: str,
        notification: Notification,
    ) -> None: ...


class NotificationOutbox(Protocol):
    async def get_pending_notifications(self, limit: int = 20) -> list[Notification]: ...

    async def mark_notification_delivered(self, event_id: str) -> None: ...

    async def mark_notification_failed(
        self,
        event_id: str,
        attempts: int,
        error: str,
        retry_delay_seconds: int,
        exhausted: bool,
    ) -> None: ...


class Notifier(Protocol):
    async def notify(self, notification: Notification) -> None: ...

    async def close(self) -> None: ...


class PendingPhraseStrategy(Protocol):
    def choose(self) -> str: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...


class IdentifierGenerator(Protocol):
    def new(self) -> str: ...


Sleep = Callable[[float], Awaitable[None]]
