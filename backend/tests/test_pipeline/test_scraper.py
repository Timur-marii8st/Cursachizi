"""Tests for web scraper."""

import pytest
import httpx
import respx

from backend.app.pipeline.research.scraper import WebScraper
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
