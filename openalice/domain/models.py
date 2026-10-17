from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    end_session: bool = False

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("Reply text must not be empty")


@dataclass(frozen=True, slots=True)
class ConversationKey:
    identity_hash: str
    generation: int

    def __post_init__(self) -> None:
        if not self.identity_hash:
            raise ValueError("Identity hash must not be empty")
        if self.generation < 0:
            raise ValueError("Conversation generation must not be negative")

    @property
    def value(self) -> str:
        return f"openalice:yandex-user:{self.identity_hash}:v{self.generation}"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Job:
    status: JobStatus
    response: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status is JobStatus.PENDING and (
            self.response is not None or self.error is not None
        ):
            raise ValueError("Pending job cannot contain a response or an error")
        if self.status is JobStatus.DONE and self.error is not None:
            raise ValueError("Completed job cannot contain an error")
        if self.status is JobStatus.FAILED and self.response is not None:
            raise ValueError("Failed job cannot contain a response")

    @classmethod
    def pending(cls) -> Job:
        return cls(JobStatus.PENDING)

    def complete(self, response: str) -> Job:
        self._require_pending()
        return Job(JobStatus.DONE, response=response)

    def fail(self, error: str) -> Job:
        self._require_pending()
        return Job(JobStatus.FAILED, error=error)

    def _require_pending(self) -> None:
        if self.status is not JobStatus.PENDING:
            raise ValueError(f"Cannot transition a {self.status.value} job")


@dataclass(frozen=True, slots=True)
class Notification:
    event_id: str
    conversation_id: str
    kind: str
    channel: str
    target: str
    text: str
    attempts: int = 0

    def __post_init__(self) -> None:
        if not self.event_id or not self.conversation_id:
            raise ValueError("Notification identity must not be empty")
        if self.attempts < 0:
            raise ValueError("Notification attempts must not be negative")
