"""Tests for query expansion."""

import json

import pytest

from backend.app.pipeline.research.query_expander import QueryExpander
from backend.app.testing import MockLLMProvider


@pytest.fixture
def expander(mock_llm: MockLLMProvider) -> QueryExpander:
    return QueryExpander(mock_llm)


class TestQueryExpander:
    async def test_successful_expansion(
        self, expander: QueryExpander, mock_llm: MockLLMProvider
    ) -> None:
        mock_llm.set_responses([
            json.dumps({
                "queries": [
                    "цифровизация управление персоналом",
                    "digital HR трансформация Россия",
                    "автоматизация HR процессов",
                    "влияние технологий на кадровый менеджмент",
                ]
            })
        ])

        queries = await expander.expand(
            topic="Цифровизация управления персоналом",
            discipline="Менеджмент",
            count=4,
        )

        assert len(queries) == 4
        assert "цифровизация управление персоналом" in queries
        assert len(mock_llm.calls) == 1

    async def test_expansion_with_json_in_code_block(
        self, expander: QueryExpander, mock_llm: MockLLMProvider
    ) -> None:
        """LLM sometimes wraps JSON in markdown code blocks."""
        mock_llm.set_responses([
            '```json\n{"queries": ["query1", "query2"]}\n```'
        ])

        queries = await expander.expand(topic="Test topic", count=2)
        assert len(queries) == 2

    async def test_fallback_on_invalid_json(
        self, expander: QueryExpander, mock_llm: MockLLMProvider
    ) -> None:
        """Should fall back to topic string if LLM returns invalid JSON."""
        mock_llm.set_responses(["This is not valid JSON at all"])

        queries = await expander.expand(topic="Тестовая тема")
        assert len(queries) == 1
        assert queries[0] == "Тестовая тема"

    async def test_respects_count_limit(
        self, expander: QueryExpander, mock_llm: MockLLMProvider
    ) -> None:
        mock_llm.set_responses([
            json.dumps({"queries": [f"query_{i}" for i in range(20)]})
        ])

        queries = await expander.expand(topic="Test", count=5)
        assert len(queries) == 5

    async def test_empty_response(
        self, expander: QueryExpander, mock_llm: MockLLMProvider
    ) -> None:
        mock_llm.set_responses([""])

        queries = await expander.expand(topic="Test topic")
        assert len(queries) == 1
        assert queries[0] == "Test topic"
