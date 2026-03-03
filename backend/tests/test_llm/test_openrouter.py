"""Tests for the OpenRouter LLM provider."""

import json

import pytest

from backend.app.llm.openrouter import OpenRouterProvider
from backend.app.llm.provider import LLMMessage


class TestOpenRouterMessageConversion:
    """Test message format conversion to OpenRouter API format."""

    def test_plain_text_message(self) -> None:
        messages = [LLMMessage(role="user", content="Hello")]
        result = OpenRouterProvider._convert_messages(messages)

        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_system_prompt_prepended(self) -> None:
        messages = [LLMMessage(role="user", content="Hi")]
        result = OpenRouterProvider._convert_messages(messages, system_prompt="You are helpful.")

        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "You are helpful."}
        assert result[1]["role"] == "user"

    def test_multimodal_message_with_images(self) -> None:
        # PNG magic bytes
        fake_png = b"\x89PNG" + b"\x00" * 100
        messages = [LLMMessage(role="user", content="Describe this", images=[fake_png])]
        result = OpenRouterProvider._convert_messages(messages)

        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "user"
        assert isinstance(msg["content"], list)
        assert len(msg["content"]) == 2
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][0]["text"] == "Describe this"
        assert msg["content"][1]["type"] == "image_url"
        assert msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_jpeg_image_detection(self) -> None:
        # JPEG magic bytes (not PNG)
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        messages = [LLMMessage(role="user", content="Check", images=[fake_jpeg])]
        result = OpenRouterProvider._convert_messages(messages)

        img_part = result[0]["content"][1]
        assert img_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_multiple_images(self) -> None:
        fake_png = b"\x89PNG" + b"\x00" * 50
        messages = [LLMMessage(role="user", content="Compare", images=[fake_png, fake_png, fake_png])]
        result = OpenRouterProvider._convert_messages(messages)

        content_parts = result[0]["content"]
        assert len(content_parts) == 4  # 1 text + 3 images

    def test_mixed_messages(self) -> None:
        fake_png = b"\x89PNG" + b"\x00" * 50
        messages = [
            LLMMessage(role="user", content="First"),
            LLMMessage(role="assistant", content="OK"),
            LLMMessage(role="user", content="Now with image", images=[fake_png]),
        ]
        result = OpenRouterProvider._convert_messages(messages)

        assert len(result) == 3
        assert isinstance(result[0]["content"], str)
        assert isinstance(result[1]["content"], str)
        assert isinstance(result[2]["content"], list)


class TestOpenRouterProvider:
    def test_default_model(self) -> None:
        provider = OpenRouterProvider(api_key="test-key")
        assert provider._default_model == "google/gemini-2.5-flash"

    def test_custom_model(self) -> None:
        provider = OpenRouterProvider(api_key="test-key", default_model="anthropic/claude-sonnet-4-5-20241022")
        assert provider._default_model == "anthropic/claude-sonnet-4-5-20241022"
