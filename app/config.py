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
    gemini_model: str = "gemini-3.5-flash-lite"
    timezone: str = "Asia/Yekaterinburg"
    min_reports_to_publish: int = Field(default=2, ge=1)
    published_state_path: str = ".runtime-state/published-source-messages.json"
    published_state_retention_days: int = Field(default=14, ge=1)
    health_state_path: str = ".runtime-state/health.json"
    admin_telegram_chat_id: int | None = None
    max_enabled: bool = False
    max_session_path: str = ".local/max/max_web_session.db"
    max_source_chat_ids: list[int] = Field(
        default_factory=lambda: [-76867728756169, -76729715050629, -76783627133571]
    )
    log_level: str = "INFO"
    dry_run: bool = False

    @field_validator("source_chats", mode="before")
    @classmethod
    def split_source_chats(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
        return value

    @field_validator("max_source_chat_ids", mode="before")
    @classmethod
    def split_max_chat_ids(cls, value: str | list[int]) -> list[int]:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
