"""Web search providers for the research pipeline."""

from abc import ABC, abstractmethod
import asyncio
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

from backend.app.utils.retry import with_http_retry
from shared.schemas.pipeline import Source

logger = structlog.get_logger()


class SearchProvider(ABC):
    """Abstract interface for web search providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[Source]:
        """Execute a search query and return sources."""
        ...

    async def aclose(self) -> None:
        """Close any underlying resources. No-op by default."""


class DuckDuckGoSearchProvider(SearchProvider):
    """DuckDuckGo HTML search provider.

    Uses the lightweight HTML endpoint to avoid API keys.
    Maintains a persistent httpx.AsyncClient for connection pooling.
    Rate-limited to ~1 request/second to avoid throttling.
    """

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    MIN_REQUEST_INTERVAL = 1.0  # seconds between requests

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            headers={"User-Agent": self.USER_AGENT},
            follow_redirects=True,
        )
        self._last_call_time: float = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_call_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            await asyncio.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_call_time = time.monotonic()

    @staticmethod
    def _extract_real_url(raw_href: str) -> str:
        """Extract the real URL from a DuckDuckGo redirect link.

        DDG wraps results in redirect URLs like:
            //duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&rut=...
        This extracts the ``uddg`` parameter value.
        """
        if raw_href.startswith("//"):
            raw_href = "https:" + raw_href

        parsed = urlparse(raw_href)
        if "duckduckgo.com" in parsed.netloc and "/l/" in parsed.path:
            qs = parse_qs(parsed.query)
            uddg_values = qs.get("uddg")
            if uddg_values:
                return unquote(uddg_values[0])

        return raw_href

    async def search(self, query: str, max_results: int = 10) -> list[Source]:
        try:
            await self._rate_limit()

            response = await self._client.get(
                self.SEARCH_URL,
                params={"q": query},
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            result_divs = soup.select("#links .result")

            sources: list[Source] = []
            for div in result_divs[:max_results]:
                link_el = div.select_one(".result__a")
                snippet_el = div.select_one(".result__snippet")

                if not link_el:
                    continue

                raw_href = link_el.get("href", "")
                if not raw_href:
                    continue

                url = self._extract_real_url(str(raw_href))
                title = link_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                sources.append(
                    Source(
                        url=url,
                        title=title,
                        snippet=snippet,
                        relevance_score=0.5,
                    )
                )

            logger.info(
                "ddg_search_complete", query=query[:80], results=len(sources)
            )
            return sources

        except Exception as e:
            logger.error("ddg_search_failed", query=query[:80], error=str(e))
            return []


class SerperSearchProvider(SearchProvider):
    """Serper.dev Google Search API — fallback provider.

    Maintains a persistent httpx.AsyncClient (PERF-001).
    """

    API_URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, max_results: int = 10) -> list[Source]:
        async def _call() -> dict:
            response = await self._client.post(
                self.API_URL,
                headers={"X-API-KEY": self._api_key},
                json={
                    "q": query,
                    "num": max_results,
                    "gl": "ru",
                    "hl": "ru",
                },
            )
            response.raise_for_status()
            return response.json()

        try:
            # TEST-005: retry on 429/5xx with exponential backoff
            data = await with_http_retry(_call)

            sources = []
            for result in data.get("organic", []):
                sources.append(
                    Source(
                        url=result.get("link", ""),
                        title=result.get("title", ""),
                        snippet=result.get("snippet", ""),
                        relevance_score=0.5,  # Serper doesn't provide relevance scores
                    )
                )

            logger.info("serper_search_complete", query=query[:80], results=len(sources))
            return sources

        except httpx.HTTPError as e:
            logger.error("serper_search_failed", query=query[:80], error=str(e))
            return []
