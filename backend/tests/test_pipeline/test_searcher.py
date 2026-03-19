"""Tests for search provider resilience and fallback behavior."""

from unittest.mock import MagicMock
from unittest.mock import AsyncMock

import httpx

from backend.app.api.deps import get_search_provider
from backend.app.pipeline.research.searcher import (
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
)
from backend.app.testing import MockSearchProvider
from shared.schemas.pipeline import Source


def _source(url: str, title: str) -> Source:
    return Source(url=url, title=title, snippet="snippet")


class TestFallbackSearchProvider:
    async def test_uses_fallback_when_primary_is_empty(self) -> None:
        primary = MockSearchProvider(results=[])
        fallback = MockSearchProvider(results=[
            _source("https://fallback.example/1", "Fallback 1"),
            _source("https://fallback.example/2", "Fallback 2"),
        ])
        provider = FallbackSearchProvider(primary=primary, fallback=fallback)

        results = await provider.search("query", max_results=5)

        assert len(results) == 2
        assert primary.queries == ["query"]
        assert fallback.queries == ["query"]

    async def test_merges_and_deduplicates_primary_and_fallback(self) -> None:
        shared = _source("https://example.com/shared", "Shared")
        primary = MockSearchProvider(results=[
            shared,
            _source("https://example.com/primary", "Primary"),
        ])
        fallback = MockSearchProvider(results=[
            shared,
            _source("https://example.com/fallback", "Fallback"),
        ])
        provider = FallbackSearchProvider(primary=primary, fallback=fallback, min_results=3)

        results = await provider.search("query", max_results=5)

        assert [item.title for item in results] == ["Shared", "Primary", "Fallback"]


class TestDuckDuckGoSearchProvider:
    async def test_circuit_breaker_opens_after_repeated_failures(self) -> None:
        provider = DuckDuckGoSearchProvider()
        provider.MIN_REQUEST_INTERVAL = 0
        provider._client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))

        try:
            for _ in range(provider.FAILURE_THRESHOLD):
                assert await provider.search("query", max_results=3) == []

            calls_before_cooldown = provider._client.get.await_count
            assert await provider.search("query", max_results=3) == []
            assert provider._client.get.await_count == calls_before_cooldown
        finally:
            await provider.aclose()


class TestGetSearchProvider:
    def test_returns_fallback_provider_when_serper_is_configured(self) -> None:
        settings = MagicMock()
        settings.serper_api_key = "serper-key"

        provider = get_search_provider(settings)

        assert isinstance(provider, FallbackSearchProvider)

    def test_returns_ddg_provider_without_serper(self) -> None:
        settings = MagicMock()
        settings.serper_api_key = ""

        provider = get_search_provider(settings)

        assert isinstance(provider, DuckDuckGoSearchProvider)
