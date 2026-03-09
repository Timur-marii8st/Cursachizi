"""Tests for HTTP retry utility (TEST-005)."""

import pytest
import httpx
import respx

from backend.app.utils.retry import with_http_retry


class TestWithHttpRetry:
    async def test_success_on_first_attempt(self) -> None:
        """No retry needed — returns result immediately."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await with_http_retry(fn)
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_429(self) -> None:
        """429 should be retried up to max_attempts."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                response = httpx.Response(429, request=httpx.Request("POST", "http://x"))
                raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
            return "ok"

        result = await with_http_retry(fn, max_attempts=3, base_delay=0.0)
        assert result == "ok"
        assert call_count == 3

    async def test_retries_on_503(self) -> None:
        """503 Service Unavailable should be retried."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = httpx.Response(503, request=httpx.Request("POST", "http://x"))
                raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)
            return "recovered"

        result = await with_http_retry(fn, max_attempts=3, base_delay=0.0)
        assert result == "recovered"
        assert call_count == 2

    async def test_does_not_retry_on_400(self) -> None:
        """400 Bad Request is not retryable — raises immediately."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            response = httpx.Response(400, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("bad request", request=response.request, response=response)

        with pytest.raises(httpx.HTTPStatusError):
            await with_http_retry(fn, max_attempts=3, base_delay=0.0)

        assert call_count == 1  # no retry for 400

    async def test_does_not_retry_on_401(self) -> None:
        """401 Unauthorized is not retryable."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            response = httpx.Response(401, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("unauthorized", request=response.request, response=response)

        with pytest.raises(httpx.HTTPStatusError):
            await with_http_retry(fn, max_attempts=3, base_delay=0.0)

        assert call_count == 1

    async def test_raises_after_all_attempts_exhausted(self) -> None:
        """Should re-raise the last exception when all retries fail."""
        async def fn() -> str:
            response = httpx.Response(502, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("bad gateway", request=response.request, response=response)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await with_http_retry(fn, max_attempts=3, base_delay=0.0)

        assert exc_info.value.response.status_code == 502

    async def test_retries_on_connect_error(self) -> None:
        """Network connect errors should be retried."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("connection refused")
            return "connected"

        result = await with_http_retry(fn, max_attempts=3, base_delay=0.0)
        assert result == "connected"
        assert call_count == 2

    async def test_respects_retry_after_header(self) -> None:
        """429 with Retry-After header: delay should use header value, not backoff."""
        delays_used: list[float] = []
        original_sleep = __import__("asyncio").sleep

        async def fake_sleep(delay: float) -> None:
            delays_used.append(delay)

        import asyncio
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = httpx.Response(
                    429,
                    headers={"retry-after": "5"},
                    request=httpx.Request("POST", "http://x"),
                )
                raise httpx.HTTPStatusError("rate limited", request=response.request, response=response)
            return "ok"

        original = asyncio.sleep
        asyncio.sleep = fake_sleep
        try:
            await with_http_retry(fn, max_attempts=3, base_delay=1.0)
        finally:
            asyncio.sleep = original

        assert delays_used == [5.0]

    async def test_single_attempt_raises_immediately(self) -> None:
        """max_attempts=1 means no retry at all."""
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            response = httpx.Response(503, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("unavailable", request=response.request, response=response)

        with pytest.raises(httpx.HTTPStatusError):
            await with_http_retry(fn, max_attempts=1, base_delay=0.0)

        assert call_count == 1
