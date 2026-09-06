from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        enable_decoding=False,
    )

    openclaw_base_url: str = "http://127.0.0.1:18789"
    openclaw_gateway_token: str = Field(min_length=1)
    openclaw_agent: str = "openclaw/default"
    openclaw_timeout_seconds: float = Field(default=300.0, gt=0, le=900)
    openalice_fake_mode: bool = False
    openalice_fake_response: str = Field(
        default="Тестовый режим работает. Запрос обработан без обращения к домашнему помощнику.",
        min_length=1,
    )
    openalice_fake_delay_seconds: float = Field(default=0.0, ge=0, le=120)
    alice_webhook_secret: str = Field(min_length=16)
    alice_allowed_user_ids: frozenset[str] = frozenset()
    alice_fast_timeout_seconds: float = Field(default=3.8, gt=0.1, lt=4.4)
    alice_max_response_chars: int = Field(default=900, ge=100, le=1024)
    alice_pending_phrases: tuple[str, ...] = Field(
        default=(
            "Мне нужно немного времени. Скажите «готово» через несколько секунд.",
            "Ответ ещё готовится. Скажите «готово» немного позже.",
        ),
        min_length=1,
    )
    notifications_enabled: bool = False
    notification_provider: Literal["home_assistant", "glagol"] = "home_assistant"
    home_assistant_url: str = "http://127.0.0.1:8123"
    home_assistant_token: str = ""
    home_assistant_entity_id: str = ""
    home_assistant_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    glagol_device_id: str = ""
    glagol_platform: str = ""
    glagol_host: str = ""
    glagol_port: int = Field(default=1961, ge=1, le=65535)
    glagol_credentials_path: Path = Path("./data/glagol_credentials.json")
    glagol_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    glagol_discovery_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    notification_ready_phrase: str = Field(
        default="Ответ готов. Скажите «готово», чтобы его услышать.",
        min_length=1,
        max_length=100,
    )
    notification_max_attempts: int = Field(default=3, ge=1, le=10)
    notification_poll_seconds: float = Field(default=5.0, ge=0.1, le=60)
    database_path: Path = Path("./openalice.db")
    log_level: str = "INFO"

    @field_validator("alice_allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_ids(cls, value: object) -> object:
        if value is None or value == "":
            return frozenset()
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("alice_pending_phrases", mode="before")
    @classmethod
    def parse_pending_phrases(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split("|") if item.strip())
        return value

    @field_validator("openclaw_base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("home_assistant_url")
    @classmethod
    def strip_home_assistant_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_notifications(self) -> "Settings":
        if self.notifications_enabled:
            if self.notification_provider == "home_assistant":
                if not self.home_assistant_token:
                    raise ValueError("HOME_ASSISTANT_TOKEN is required for Home Assistant notifications")
                if not self.home_assistant_entity_id:
                    raise ValueError("HOME_ASSISTANT_ENTITY_ID is required for Home Assistant notifications")
            elif not self.glagol_device_id:
                raise ValueError("GLAGOL_DEVICE_ID is required for Glagol notifications")
            elif self.glagol_host and not self.glagol_platform:
                raise ValueError("GLAGOL_PLATFORM is required when GLAGOL_HOST is set")
        return self

    @property
    def notification_channel(self) -> str:
        return self.notification_provider

    @property
    def notification_target(self) -> str:
        if self.notification_provider == "glagol":
            return self.glagol_device_id
        return self.home_assistant_entity_id


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
