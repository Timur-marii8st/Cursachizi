"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://courseforge:courseforge@localhost:5432/courseforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM Providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    default_llm_provider: str = "anthropic"
    default_writer_model: str = "claude-sonnet-4-5-20241022"
    default_light_model: str = "claude-haiku-4-5-20241022"

    # Search Providers
    tavily_api_key: str = ""
    serper_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # Object Storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "courseforge-documents"
    s3_region: str = "us-east-1"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"

    # Rate Limiting
    rate_limit_per_user: str = "10/hour"

    # Pipeline
    max_search_results: int = 20
    max_sources_per_topic: int = 15
    max_tokens_per_section: int = 4000
    pipeline_timeout_seconds: int = 900

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
