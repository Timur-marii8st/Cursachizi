"""OpenRouter LLM provider — unified API for multiple model providers.

OpenRouter provides access to Claude, GPT, Gemini, and others through
a single OpenAI-compatible API endpoint. This is the recommended provider
for CourseForge as it simplifies API key management and model switching.
"""

import base64
import json

import httpx
import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider, LLMResponse
from backend.app.utils.retry import with_http_retry

logger = structlog.get_logger()


class OpenRouterProvider(LLMProvider):
    """LLM provider using OpenRouter's unified API.

    OpenRouter is OpenAI-compatible, so we use the same chat completions format.
    Vision messages are supported via base64-encoded images in content arrays.

    The provider maintains a persistent httpx.AsyncClient (PERF-001) to reuse
    TCP/TLS connections across multiple generate() calls within the same job.
    """

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    DEFAULT_MODEL = "google/google/gemini-3.1-flash-lite-preview"

    def __init__(
        self,
        api_key: str,
        default_model: str | None = None,
        app_name: str = "CourseForge",
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model or self.DEFAULT_MODEL
        self._app_name = app_name
        # Persistent client — reused across all calls within this provider instance.
        # Avoids per-call TLS handshake overhead (PERF-001).
        self._client = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

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
        api_messages = self._convert_messages(messages, system_prompt)
        used_model = model or self._default_model

        async def _call() -> dict:
            response = await self._client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://courseforge.ru",
                    "X-Title": self._app_name,
                    "Content-Type": "application/json",
                },
                json={
                    "model": used_model,
                    "messages": api_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            if response.status_code >= 400:
                logger.error(
                    "openrouter_api_error",
                    status=response.status_code,
                    model=used_model,
                )
            response.raise_for_status()
            return response.json()

        # TEST-005: retry on 429/5xx with exponential backoff
        data = await with_http_retry(_call)

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"] or "",
            model=data.get("model", used_model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", ""),
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
        full_system = (
            f"{system_prompt}\n\n{schema_instruction}" if system_prompt else schema_instruction
        )

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

    async def generate_with_vision(
        self,
        prompt: str,
        images: list[bytes],
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response using a vision model with image inputs.

        This is a convenience method that builds the multimodal message format.

        Args:
            prompt: Text prompt to accompany the images.
            images: List of PNG/JPEG image bytes.
            model: Vision-capable model (defaults to google/gemini-3.1-flash-lite-preview).
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.

        Returns:
            LLMResponse with model's analysis of the images.
        """
        message = LLMMessage(role="user", content=prompt, images=images)
        return await self.generate(
            [message],
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _convert_messages(
        messages: list[LLMMessage], system_prompt: str | None = None
    ) -> list[dict]:
        """Convert LLMMessage objects to OpenRouter/OpenAI API format.

        Handles multimodal messages with images by using the content array format.
        """
        api_messages: list[dict] = []

        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.images:
                # Multimodal message — use content array with text + image_url parts
                content_parts: list[dict] = [
                    {"type": "text", "text": msg.content},
                ]
                for img_bytes in msg.images:
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    # Detect MIME type from magic bytes
                    mime = "image/png" if img_bytes[:4] == b"\x89PNG" else "image/jpeg"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                        },
                    })
                api_messages.append({"role": msg.role, "content": content_parts})
            else:
                # Plain text message
                api_messages.append({"role": msg.role, "content": msg.content})

        return api_messages
