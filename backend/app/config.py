"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: two levels up from this file (backend/app/config.py → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://courseforge:courseforge@localhost:5433/courseforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM Providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    default_llm_provider: str = "openrouter"
    default_writer_model: str = "google/google/gemini-3.1-flash-lite-preview"
    default_light_model: str = "stepfun/step-3.5-flash"
    vision_model: str = "google/google/gemini-3.1-flash-lite-preview"

    # Search Providers
    tavily_api_key: str = ""
    serper_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # Object Storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_name: str = "courseforge-documents"
    s3_region: str = "us-east-1"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    internal_api_key: str = ""

    # Admin
    # Comma-separated Telegram IDs with unlimited credits (e.g. "123456789,987654321")
    admin_telegram_ids: str = ""

    # Rate Limiting
    rate_limit_per_user: str = "10/hour"
    # Comma-separated list of trusted reverse proxy IPs (e.g. "10.0.0.1,172.16.0.2").
    # X-Forwarded-For is only trusted when the connecting IP is in this list (SEC-002).
    trusted_proxy_ips: str = ""

    # Pipeline
    max_search_results: int = 20
    max_sources_per_topic: int = 15
    max_tokens_per_section: int = 4000
    pipeline_timeout_seconds: int = 900

    # Visual template matching
    visual_match_max_iterations: int = 3
    visual_match_enabled: bool = True

    # Iterative fact-checking
    fact_check_max_rounds: int = 2

    # Translation API (for humanizer)
    google_translate_api_key: str = ""
    deepl_api_key: str = ""

    # Robokassa payment
    robokassa_login: str = ""
    robokassa_password1: str = ""
    robokassa_password2: str = ""
    robokassa_test_mode: bool = True

    @property
    def admin_telegram_id_set(self) -> frozenset[int]:
        """Parsed set of admin Telegram IDs (unlimited credits)."""
        if not self.admin_telegram_ids.strip():
            return frozenset()
        result = set()
        for part in self.admin_telegram_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return frozenset(result)

    @property
    def trusted_proxies(self) -> frozenset[str]:
        """Parsed set of trusted proxy IP addresses."""
        if not self.trusted_proxy_ips.strip():
            return frozenset()
        return frozenset(ip.strip() for ip in self.trusted_proxy_ips.split(",") if ip.strip())

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        if self.app_env == "production" and not self.internal_api_key.strip():
            raise ValueError(
                "INTERNAL_API_KEY must be set in production. "
                "This protects the Jobs API from unauthorized access."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
