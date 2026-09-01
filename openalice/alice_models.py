from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AliceRequestData(BaseModel):
    model_config = ConfigDict(extra="allow")

    command: str = ""
    original_utterance: str = ""
    type: str = "SimpleUtterance"


class AliceApplication(BaseModel):
    model_config = ConfigDict(extra="allow")

    application_id: str


class AliceUser(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str


class AliceSession(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: int | str
    session_id: str
    skill_id: str = "unknown"
    new: bool = False
    application: AliceApplication
    user: AliceUser | None = None


class AliceWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    request: AliceRequestData
    session: AliceSession
    version: str = "1.0"
    state: dict[str, Any] = Field(default_factory=dict)


class AliceResponseBody(BaseModel):
    text: str
    tts: str | None = None
    end_session: bool = False


class AliceWebhookResponse(BaseModel):
    response: AliceResponseBody
    version: str = "1.0"

