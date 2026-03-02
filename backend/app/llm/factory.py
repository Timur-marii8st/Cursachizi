"""Factory for creating LLM provider instances."""

from backend.app.llm.provider import LLMProvider


def create_llm_provider(
    provider: str,
    api_key: str,
    default_model: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: Provider name ("anthropic" or "openai").
        api_key: API key for the provider.
        default_model: Optional default model override.

    Returns:
        Configured LLMProvider instance.

    Raises:
        ValueError: If provider name is not recognized.
    """
    if provider == "anthropic":
        from backend.app.llm.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=api_key, default_model=default_model)
    elif provider == "openai":
        from backend.app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=api_key, default_model=default_model)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. Supported: 'anthropic', 'openai'"
        )
