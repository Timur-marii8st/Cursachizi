"""Tests for API dependency helpers."""

from unittest.mock import patch

from backend.app.api.deps import get_search_provider
from backend.app.pipeline.research.searcher import (
    DuckDuckGoSearchProvider,
    FallbackSearchProvider,
    SerperSearchProvider,
)
from backend.app.config import Settings


class TestGetSearchProvider:
    def test_prefers_serper_when_api_key_present(self) -> None:
        settings = Settings(serper_api_key="serper-secret", tavily_api_key="")

        provider = get_search_provider(settings)

        assert isinstance(provider, FallbackSearchProvider)
        assert isinstance(provider._primary, SerperSearchProvider)
        assert isinstance(provider._fallback, DuckDuckGoSearchProvider)
        assert provider._primary._api_key == "serper-secret"

    def test_falls_back_to_duckduckgo_when_serper_missing(self) -> None:
        settings = Settings(serper_api_key="", tavily_api_key="")

        provider = get_search_provider(settings)

        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_ignores_whitespace_only_serper_key(self) -> None:
        settings = Settings(serper_api_key="   ", tavily_api_key="")

        provider = get_search_provider(settings)

        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_uses_default_settings_lookup_when_not_provided(self) -> None:
        settings = Settings(serper_api_key="serper-secret", tavily_api_key="")

        with patch("backend.app.api.deps.get_settings", return_value=settings):
            provider = get_search_provider()

        assert isinstance(provider, FallbackSearchProvider)
        assert isinstance(provider._primary, SerperSearchProvider)
