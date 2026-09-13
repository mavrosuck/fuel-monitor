from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_api_id: int
    telegram_api_hash: SecretStr
    telethon_session_name: str = "fuel_monitor"
    source_chats: list[str] = Field(default_factory=lambda: ["GdeBenzin56", "benzin156ru"])
    bot_token: SecretStr | None = None
    target_channel: str = "@benzinoren"
    gemini_api_key: SecretStr
    gemini_model: str = "gemini-2.5-flash-lite"
    timezone: str = "Asia/Yekaterinburg"
    min_reports_to_publish: int = Field(default=5, ge=1)
    log_level: str = "INFO"
    dry_run: bool = False

    @field_validator("source_chats", mode="before")
    @classmethod
    def split_source_chats(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
