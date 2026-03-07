"""Tests for LLM provider factory."""

import pytest

from backend.app.llm.anthropic import AnthropicProvider
from backend.app.llm.factory import create_llm_provider
from backend.app.llm.openai_provider import OpenAIProvider


class TestLLMFactory:
    def test_create_anthropic_provider(self) -> None:
        provider = create_llm_provider("anthropic", api_key="test-key")
        assert isinstance(provider, AnthropicProvider)

    def test_create_openai_provider(self) -> None:
        provider = create_llm_provider("openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_create_with_custom_model(self) -> None:
        provider = create_llm_provider(
            "anthropic",
            api_key="test-key",
            default_model="claude-haiku-4-5-20241022",
        )
        assert isinstance(provider, AnthropicProvider)
        assert provider._default_model == "claude-haiku-4-5-20241022"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_provider("unknown", api_key="test-key")

    def test_error_message_includes_provider_name(self) -> None:
        with pytest.raises(ValueError, match="'foobar'"):
            create_llm_provider("foobar", api_key="test-key")
