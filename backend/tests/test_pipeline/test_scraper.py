"""Tests for web scraper."""

import httpx
import pytest
import respx

from backend.app.pipeline.research.scraper import WebScraper, _is_safe_url
from shared.schemas.pipeline import Source


@pytest.fixture
def scraper() -> WebScraper:
    return WebScraper(timeout=5.0, max_concurrent=2)


class TestWebScraper:
    async def test_skips_sources_with_content(self, scraper: WebScraper) -> None:
        """Sources that already have full_text should not be re-scraped."""
        sources = [
            Source(
                url="https://example.com",
                title="Already scraped",
                full_text="Existing content that should not change",
            ),
        ]

        result = await scraper.scrape_sources(sources)
        assert result[0].full_text == "Existing content that should not change"

    async def test_skips_sources_without_url(self, scraper: WebScraper) -> None:
        sources = [Source(url="", title="No URL")]
        result = await scraper.scrape_sources(sources)
        assert result[0].full_text == ""

    @respx.mock
    async def test_handles_http_errors(self, scraper: WebScraper) -> None:
        """HTTP errors should be caught gracefully."""
        respx.get("https://broken.com/page").mock(
            return_value=httpx.Response(500)
        )

        sources = [Source(url="https://broken.com/page", title="Broken")]
        result = await scraper.scrape_sources(sources)
        assert result[0].full_text == ""

    async def test_concurrent_limit(self) -> None:
        """Verify the semaphore limits concurrency."""
        scraper = WebScraper(max_concurrent=1)
        assert scraper._semaphore._value == 1

    async def test_ssrf_blocked_internal_url(self, scraper: WebScraper) -> None:
        """SSRF: internal URLs should be silently skipped (full_text stays empty)."""
        sources = [Source(url="http://192.168.1.1/admin", title="Internal")]
        result = await scraper.scrape_sources(sources)
        assert result[0].full_text == ""

    async def test_ssrf_blocked_loopback(self, scraper: WebScraper) -> None:
        """SSRF: loopback addresses must be blocked."""
        sources = [Source(url="http://127.0.0.1:8000/api/secret", title="Loopback")]
        result = await scraper.scrape_sources(sources)
        assert result[0].full_text == ""

    async def test_ssrf_blocked_non_http_scheme(self, scraper: WebScraper) -> None:
        """SSRF: non-HTTP schemes must be blocked."""
        assert _is_safe_url("file:///etc/passwd") is False
        assert _is_safe_url("ftp://example.com/file") is False

    async def test_ssrf_allows_public_url(self) -> None:
        """SSRF: public internet URLs must pass the check."""
        assert _is_safe_url("https://google.com") is True
        assert _is_safe_url("http://example.com/page") is True

    async def test_ssrf_is_safe_url_invalid_input(self) -> None:
        """SSRF: malformed URLs return False without raising."""
        assert _is_safe_url("not-a-url") is False
        assert _is_safe_url("") is False
