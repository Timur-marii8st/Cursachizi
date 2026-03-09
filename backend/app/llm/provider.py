"""Abstract LLM provider interface.

All LLM interactions go through this interface, making it easy
to swap providers without touching pipeline code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    role: str  # "user", "assistant", "system"
    content: str
    images: list[bytes] = field(default_factory=list)  # PNG/JPEG bytes for vision models


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    async def aclose(self) -> None:
        """Close any underlying resources (e.g. HTTP client). No-op by default."""

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a completion from a list of messages."""
        ...

    @abstractmethod
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
        """Generate a completion that conforms to a JSON schema.

        The response content will be a valid JSON string matching response_schema.
        """
        ...
