"""FastAPI dependency injection — shared dependencies for route handlers."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings, get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.llm.factory import create_llm_provider
from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.research.searcher import (
    SearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Get the configured LLM provider."""
    settings = settings or get_settings()

    if settings.default_llm_provider == "anthropic" and settings.anthropic_api_key:
        return create_llm_provider(
            "anthropic",
            api_key=settings.anthropic_api_key,
            default_model=settings.default_writer_model,
        )
    elif settings.default_llm_provider == "openai" and settings.openai_api_key:
        return create_llm_provider(
            "openai",
            api_key=settings.openai_api_key,
            default_model=settings.default_writer_model,
        )
    else:
        # Try anthropic first, then openai
        if settings.anthropic_api_key:
            return create_llm_provider("anthropic", api_key=settings.anthropic_api_key)
        elif settings.openai_api_key:
            return create_llm_provider("openai", api_key=settings.openai_api_key)
        raise ValueError(
            "No LLM provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        )


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Get the configured search provider."""
    settings = settings or get_settings()

    if settings.tavily_api_key:
        return TavilySearchProvider(api_key=settings.tavily_api_key)
    elif settings.serper_api_key:
        return SerperSearchProvider(api_key=settings.serper_api_key)
    else:
        raise ValueError(
            "No search provider configured. Set TAVILY_API_KEY or SERPER_API_KEY."
        )
