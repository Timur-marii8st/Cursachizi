"""Web search providers for the research pipeline."""

from abc import ABC, abstractmethod

import httpx
import structlog

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


class TavilySearchProvider(SearchProvider):
    """Tavily AI search — provides structured results optimized for AI consumption.

    Maintains a persistent httpx.AsyncClient (PERF-001) to reuse TCP/TLS connections
    across multiple search() calls within the same pipeline run.
    """

    API_URL = "https://api.tavily.com/search"

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
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_raw_content": True,
                },
            )
            response.raise_for_status()
            return response.json()

        try:
            # TEST-005: retry on 429/5xx with exponential backoff
            data = await with_http_retry(_call)

            sources = []
            for result in data.get("results", []):
                sources.append(
                    Source(
                        url=result.get("url", ""),
                        title=result.get("title", ""),
                        snippet=result.get("content", "")[:500],
                        full_text=result.get("raw_content", "") or result.get("content", ""),
                        relevance_score=result.get("score", 0.0),
                    )
                )

            logger.info("tavily_search_complete", query=query[:80], results=len(sources))
            return sources

        except httpx.HTTPError as e:
            logger.error("tavily_search_failed", query=query[:80], error=str(e))
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
