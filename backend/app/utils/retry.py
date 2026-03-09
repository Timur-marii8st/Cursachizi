"""HTTP retry utility with exponential backoff.

Used by LLM and search providers to handle transient failures:
- 429 Too Many Requests (rate limited) — respects Retry-After header
- 500/502/503/504 Server errors — transient upstream issues
- Network errors (connect timeout, connection reset)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes that are safe to retry
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


async def with_http_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """Retry an async callable on transient HTTP and network errors.

    Uses exponential backoff: delay doubles each attempt, capped at max_delay.
    For 429 responses, Retry-After header is respected when present.

    Args:
        fn: Zero-argument async callable to retry.
        max_attempts: Total number of attempts (including the first).
        base_delay: Initial delay in seconds before the second attempt.
        max_delay: Maximum delay cap in seconds.

    Returns:
        The return value of fn() on success.

    Raises:
        The last exception if all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await fn()

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUSES:
                raise  # non-retryable (400, 401, 403, 404, …)

            last_exc = exc

            # Respect Retry-After header for 429 rate-limit responses
            retry_after = exc.response.headers.get("retry-after", "")
            try:
                delay = float(retry_after)
            except (ValueError, TypeError):
                delay = min(base_delay * (2**attempt), max_delay)

            logger.warning(
                "http_retry",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "status": exc.response.status_code,
                    "delay": delay,
                },
            )

        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning(
                "http_retry_network",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "error": str(exc),
                    "delay": delay,
                },
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
