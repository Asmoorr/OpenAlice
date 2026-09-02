from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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

    @field_validator("openclaw_base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
