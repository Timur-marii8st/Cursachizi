"""OpenAI LLM provider implementation."""

import json

import openai

from backend.app.llm.provider import LLMMessage, LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """LLM provider using OpenAI's API."""

    DEFAULT_MODEL = "gpt-4.1"

    def __init__(self, api_key: str, default_model: str | None = None) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._default_model = default_model or self.DEFAULT_MODEL

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.close()

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages, system_prompt)

        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            finish_reason=choice.finish_reason or "",
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

        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]).strip()

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            finish_reason=response.finish_reason,
        )

    @staticmethod
    def _convert_messages(
        messages: list[LLMMessage], system_prompt: str | None = None
    ) -> list[dict]:
        api_messages: list[dict] = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            api_messages.append({"role": msg.role, "content": msg.content})
        return api_messages
