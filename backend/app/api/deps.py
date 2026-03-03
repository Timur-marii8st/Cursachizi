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

    provider = settings.default_llm_provider

    if provider == "openrouter" and settings.openrouter_api_key:
        return create_llm_provider(
            "openrouter",
            api_key=settings.openrouter_api_key,
            default_model=settings.default_writer_model,
        )
    elif provider == "anthropic" and settings.anthropic_api_key:
        return create_llm_provider(
            "anthropic",
            api_key=settings.anthropic_api_key,
            default_model=settings.default_writer_model,
        )
    elif provider == "openai" and settings.openai_api_key:
        return create_llm_provider(
            "openai",
            api_key=settings.openai_api_key,
            default_model=settings.default_writer_model,
        )
    else:
        # Fallback chain: openrouter → anthropic → openai
        if settings.openrouter_api_key:
            return create_llm_provider(
                "openrouter", api_key=settings.openrouter_api_key
            )
        elif settings.anthropic_api_key:
            return create_llm_provider("anthropic", api_key=settings.anthropic_api_key)
        elif settings.openai_api_key:
            return create_llm_provider("openai", api_key=settings.openai_api_key)
        raise ValueError(
            "No LLM provider configured. Set OPENROUTER_API_KEY, "
            "ANTHROPIC_API_KEY, or OPENAI_API_KEY."
        )


def get_vision_llm_provider(settings: Settings | None = None):
    """Get an OpenRouter provider for vision tasks (visual template matching)."""
    from backend.app.llm.openrouter import OpenRouterProvider

    settings = settings or get_settings()
    if not settings.openrouter_api_key:
        return None
    return OpenRouterProvider(
        api_key=settings.openrouter_api_key,
        default_model=settings.vision_model,
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
