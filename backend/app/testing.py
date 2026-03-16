"""Test utilities — mock implementations for testing pipeline components."""

from backend.app.llm.provider import LLMMessage, LLMProvider, LLMResponse
from backend.app.pipeline.research.searcher import SearchProvider
from shared.schemas.pipeline import Source


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that returns predetermined responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_index = 0
        self.calls: list[dict] = []

    def set_responses(self, responses: list[str]) -> None:
        self._responses = responses
        self._call_index = 0

    def set_response(self, response: str) -> None:
        """Convenience alias: set a single response (documented in CLAUDE.md)."""
        self.set_responses([response])

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append({
            "messages": messages,
            "model": model,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

        if self._call_index >= len(self._responses):
            raise AssertionError(
                f"MockLLMProvider: call #{self._call_index} not configured "
                f"(only {len(self._responses)} responses provided)"
            )
        content = self._responses[self._call_index]
        self._call_index += 1

        return LLMResponse(
            content=content,
            model=model or "mock-model",
            input_tokens=100,
            output_tokens=50,
        )

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        response_schema: dict,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        return await self.generate(
            messages,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class MockSearchProvider(SearchProvider):
    """Mock search provider returning predetermined results."""

    def __init__(self, results: list[Source] | None = None) -> None:
        self._results = results or []
        self.queries: list[str] = []

    def set_results(self, results: list[Source]) -> None:
        self._results = results

    async def search(self, query: str, max_results: int = 10) -> list[Source]:
        self.queries.append(query)
        return self._results[:max_results]
