"""Tests for LLM provider interface and mock."""


from backend.app.llm.provider import LLMMessage, LLMResponse
from backend.app.testing import MockLLMProvider


class TestLLMResponse:
    def test_total_tokens(self) -> None:
        response = LLMResponse(
            content="test",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
        )
        assert response.total_tokens == 150

    def test_default_values(self) -> None:
        response = LLMResponse(content="test", model="m")
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.total_tokens == 0
        assert response.finish_reason == ""


class TestMockLLMProvider:
    async def test_returns_responses_in_order(self) -> None:
        mock = MockLLMProvider(responses=["first", "second", "third"])

        r1 = await mock.generate([LLMMessage(role="user", content="q1")])
        r2 = await mock.generate([LLMMessage(role="user", content="q2")])
        r3 = await mock.generate([LLMMessage(role="user", content="q3")])

        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "third"

    async def test_returns_empty_when_exhausted(self) -> None:
        mock = MockLLMProvider(responses=["only_one"])

        r1 = await mock.generate([LLMMessage(role="user", content="q1")])
        r2 = await mock.generate([LLMMessage(role="user", content="q2")])

        assert r1.content == "only_one"
        assert r2.content == ""

    async def test_tracks_calls(self) -> None:
        mock = MockLLMProvider(responses=["r"])

        await mock.generate(
            [LLMMessage(role="user", content="hello")],
            model="custom-model",
            temperature=0.5,
        )

        assert len(mock.calls) == 1
        assert mock.calls[0]["model"] == "custom-model"
        assert mock.calls[0]["temperature"] == 0.5

    async def test_set_responses_resets_index(self) -> None:
        mock = MockLLMProvider(responses=["old"])
        await mock.generate([LLMMessage(role="user", content="q")])

        mock.set_responses(["new1", "new2"])
        r = await mock.generate([LLMMessage(role="user", content="q")])
        assert r.content == "new1"
