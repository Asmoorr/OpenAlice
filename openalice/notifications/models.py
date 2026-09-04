from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    event_id: str
    conversation_id: str
    kind: str
    channel: str
    target: str
    text: str
    attempts: int = 0
