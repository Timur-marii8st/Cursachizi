"""Anthropic (Claude) LLM provider implementation."""

import json

import anthropic

from backend.app.llm.provider import LLMMessage, LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    """LLM provider using Anthropic's Claude API."""

    DEFAULT_MODEL = "claude-sonnet-4-5-20241022"

    def __init__(self, api_key: str, default_model: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model or self.DEFAULT_MODEL

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)

        return LLMResponse(
            content=response.content[0].text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            finish_reason=response.stop_reason or "",
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
        schema_instruction = (
            "You must respond with valid JSON that conforms to this schema:\n"
            f"```json\n{json.dumps(response_schema, ensure_ascii=False, indent=2)}\n```\n"
            "Respond ONLY with the JSON object, no other text."
        )
        full_system = f"{system_prompt}\n\n{schema_instruction}" if system_prompt else schema_instruction

        response = await self.generate(
            messages,
            model=model,
            system_prompt=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Strip markdown code fences if present
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last line (```json and ```)
            content = "\n".join(lines[1:-1]).strip()

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            finish_reason=response.finish_reason,
        )

    @staticmethod
    def _convert_messages(messages: list[LLMMessage]) -> list[dict]:
        """Convert LLMMessage objects to Anthropic API format.

        Filters out system messages since they're handled via the system parameter.
        """
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role != "system"
        ]
