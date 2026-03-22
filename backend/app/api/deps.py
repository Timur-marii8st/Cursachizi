"""FastAPI dependency injection — shared dependencies for route handlers."""

import hmac
from collections.abc import AsyncGenerator

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings, get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.llm.factory import create_llm_provider
from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.research.searcher import (
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    SearchProvider,
    SerperSearchProvider,
)

# Atomic increment + conditional expire using Lua.
# Eliminates the race condition between INCR and EXPIRE: if the process dies
# after INCR but before EXPIRE the key would never expire, breaking rate
# limiting permanently.  The script executes as a single Redis transaction.
_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _parse_rate_limit(value: str) -> tuple[int, int]:
    """Parse limits like `10/hour` into `(limit, window_seconds)`."""
    try:
        raw_count, raw_period = value.strip().split("/", maxsplit=1)
        count = int(raw_count)
    except Exception as exc:
        raise ValueError(f"Invalid rate limit format: {value}") from exc

    periods = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }
    window = periods.get(raw_period.strip().lower())
    if count < 1 or window is None:
        raise ValueError(f"Unsupported rate limit value: {value}")
    return count, window


async def enforce_job_rate_limit(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    """Apply per-client rate limit to expensive job creation endpoint."""
    settings = get_settings()
    try:
        max_requests, window_seconds = _parse_rate_limit(settings.rate_limit_per_user)
    except ValueError:
        max_requests, window_seconds = 10, 3600

    # SEC-002: only trust X-Forwarded-For when the direct connecting IP
    # is a known reverse proxy.  Without this check, any client can spoof
    # the header and rotate their apparent IP to bypass rate limiting.
    #
    # SEC-003: never use the raw X-API-Key header value as the rate-limit
    # bucket key without first verifying it matches the configured secret.
    # An attacker could otherwise rotate arbitrary strings in that header to
    # get an unlimited number of independent rate-limit buckets, completely
    # bypassing the per-client limit.  We check the key here only to decide
    # which identifier to use; rejection of invalid keys is still the sole
    # responsibility of verify_internal_api_key().
    expected_key = settings.internal_api_key.strip()
    key_is_valid = bool(expected_key) and hmac.compare_digest(x_api_key or "", expected_key)

    client_host = request.client.host if request.client else "unknown"
    if key_is_valid:
        # Authenticated bot request — use the shared key as the bucket so
        # all legitimate bot traffic shares one limit, regardless of origin IP.
        client_id = "internal_bot"
    elif client_host in settings.trusted_proxies:
        client_id = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or client_host
        )
    else:
        client_id = client_host
    rate_key = f"rate:jobs:{client_id}"

    redis_pool = getattr(request.app.state, "redis_pool", None)
    if redis_pool is None:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter unavailable",
            )
        # Dev mode: skip rate limiting when Redis is not available.
        return

    try:
        current = int(
            await redis_pool.eval(_RATE_LIMIT_SCRIPT, 1, rate_key, str(window_seconds))
        )
        ttl_seconds = await redis_pool.ttl(rate_key)
    except Exception as exc:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiter unavailable",
            ) from exc
        return

    if current > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry in {max(ttl_seconds, 0)} seconds.",
        )


def verify_internal_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protect internal API endpoints when INTERNAL_API_KEY is configured."""
    settings = get_settings()
    expected_key = settings.internal_api_key.strip()

    if not expected_key:
        return

    if not hmac.compare_digest(x_api_key or "", expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


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


_vision_llm_provider = None  # OpenRouterProvider | None — lazy import below


def get_vision_llm_provider(settings: Settings | None = None):
    """Get an OpenRouter provider for vision tasks (visual template matching).

    The provider is constructed once and reused for the lifetime of the
    process.  Creating a new provider on every call is wasteful: it
    re-initialises the underlying HTTP client and any connection pool.
    """
    from backend.app.llm.openrouter import OpenRouterProvider

    global _vision_llm_provider

    settings = settings or get_settings()
    if not settings.openrouter_api_key:
        return None

    if _vision_llm_provider is None:
        _vision_llm_provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            default_model=settings.vision_model,
        )
    return _vision_llm_provider


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Get the configured search provider.

    Prefer Serper when available because it is more reliable and materially
    faster than scraping DuckDuckGo HTML. Keep DuckDuckGo as a no-key fallback.
    """
    settings = settings or get_settings()

    if settings.serper_api_key.strip():
        return FallbackSearchProvider(
            primary=SerperSearchProvider(api_key=settings.serper_api_key),
            fallback=DuckDuckGoSearchProvider(),
            min_results=3,
        )
    return DuckDuckGoSearchProvider()
