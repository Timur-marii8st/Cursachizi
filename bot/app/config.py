"""Telegram bot configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""
    telegram_api_proxy: str = ""  # e.g. socks5://user:pass@host:port or http://host:port
    api_base_url: str = "http://localhost:8000"
    redis_url: str = "redis://localhost:6379/0"
    internal_api_key: str = ""


@lru_cache(maxsize=1)
def get_bot_settings() -> BotSettings:
    return BotSettings()
