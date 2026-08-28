from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_api_id: int
    telegram_api_hash: SecretStr
    telegram_phone: str
    telethon_session_name: str = "fuel_monitor"
    source_chats: list[str] = Field(default_factory=lambda: ["GdeBenzin56", "benzin156ru"])
    bot_token: SecretStr
    target_channel: str = "@benzinoren"
    openai_api_key: SecretStr
    openai_model: str
    database_url: str
    timezone: str = "Asia/Yekaterinburg"  # IANA zone for Orenburg (UTC+5)
    min_reports_to_publish: int = Field(default=5, ge=1)
    schedule_minute: int = Field(default=0, ge=0, le=59)
    schedule_second: int = Field(default=5, ge=0, le=59)
    log_level: str = "INFO"
    health_port: int = Field(default=8080, ge=1, le=65535)

    @field_validator("source_chats", mode="before")
    @classmethod
    def split_source_chats(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
