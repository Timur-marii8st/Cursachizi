"""Tests for outline generation."""

import json

import pytest

from backend.app.pipeline.writer.outliner import Outliner
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import ResearchResult, Source


@pytest.fixture
def outliner(mock_llm: MockLLMProvider) -> Outliner:
    return Outliner(mock_llm)


@pytest.fixture
def sample_research() -> ResearchResult:
    return ResearchResult(
        original_topic="Цифровизация управления персоналом",
        expanded_queries=["query1", "query2"],
        sources=[
            Source(
                url="https://example.com",
                title="Тестовый источник",
                snippet="Тестовое описание",
            )
        ],
    )


class TestOutliner:
    async def test_successful_outline_generation(
        self,
        outliner: Outliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        mock_llm.set_responses([
            json.dumps({
                "title": "Цифровизация управления персоналом в российских компаниях",
                "introduction_points": [
                    "Актуальность цифровой трансформации HR",
                    "Цель: исследовать влияние цифровизации",
                ],
                "chapters": [
                    {
                        "number": 1,
                        "title": "Теоретические основы цифровизации HR",
                        "subsections": [
                            "1.1 Понятие цифровизации HR",
                            "1.2 Основные направления digital HR",
                        ],
                        "description": "Обзор литературы",
                        "estimated_pages": 10,
                    },
                    {
                        "number": 2,
                        "title": "Анализ практик цифровизации HR в России",
                        "subsections": [
                            "2.1 Текущее состояние",
                            "2.2 Кейсы российских компаний",
                        ],
                        "description": "Практический анализ",
                        "estimated_pages": 12,
                    },
                ],
                "conclusion_points": ["Выводы по цифровизации HR"],
            })
        ])

        outline = await outliner.generate(
            topic="Цифровизация управления персоналом",
            discipline="Менеджмент",
            page_count=30,
            research=sample_research,
        )

        assert "Цифровизация" in outline.title
        assert len(outline.chapters) == 2
        assert outline.chapters[0].number == 1
        assert len(outline.chapters[0].subsections) == 2
        assert len(outline.introduction_points) == 2
        assert len(outline.conclusion_points) >= 1

    async def test_fallback_on_invalid_json(
        self,
        outliner: Outliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        mock_llm.set_responses(["not valid json"])

        outline = await outliner.generate(
            topic="Тестовая тема",
            discipline="",
            page_count=30,
            research=sample_research,
        )

        # Should return a default outline
        assert outline.title == "Тестовая тема"
        assert len(outline.chapters) == 3

    async def test_custom_outline_included_in_prompt(
        self,
        outliner: Outliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """Custom outline text should appear in the LLM prompt."""
        mock_llm.set_responses([
            json.dumps({
                "title": "Валюта и валютные ценности",
                "introduction_points": ["Актуальность"],
                "chapters": [
                    {
                        "number": 1,
                        "title": "Понятие валюты по российскому законодательству",
                        "subsections": [
                            "1.1 Экономическая и правовая сущность валюты",
                            "1.2 Виды валюты в российском законодательстве",
                        ],
                        "description": "Теория",
                        "estimated_pages": 10,
                    },
                ],
                "conclusion_points": ["Выводы"],
            })
        ])

        custom_plan = (
            "Глава 1. Понятие валюты по российскому законодательству\n"
            "1.1. Экономическая и правовая сущность валюты\n"
            "1.2. Виды валюты в российском законодательстве"
        )

        outline = await outliner.generate(
            topic="Валюта и валютные ценности",
            discipline="Финансовое право",
            page_count=35,
            research=sample_research,
            custom_outline=custom_plan,
        )

        # Verify the custom plan was sent to LLM
        assert len(mock_llm.calls) == 1
        sent_prompt = mock_llm.calls[0]["messages"][0].content
        assert "ПОЛЬЗОВАТЕЛЬСКИЙ ПЛАН" in sent_prompt
        assert "Экономическая и правовая сущность валюты" in sent_prompt

        # Verify outline was parsed correctly
        assert len(outline.chapters) == 1
        assert "валют" in outline.chapters[0].title.lower()

    async def test_no_custom_outline_block_when_empty(
        self,
        outliner: Outliner,
        mock_llm: MockLLMProvider,
        sample_research: ResearchResult,
    ) -> None:
        """When custom_outline is empty, the prompt should not contain the block."""
        mock_llm.set_responses([
            json.dumps({
                "title": "Тест",
                "introduction_points": ["Актуальность"],
                "chapters": [
                    {
                        "number": 1,
                        "title": "Глава 1",
                        "subsections": ["1.1 Подраздел"],
                        "description": "Описание",
                        "estimated_pages": 10,
                    },
                ],
                "conclusion_points": ["Выводы"],
            })
        ])

        await outliner.generate(
            topic="Тест",
            discipline="",
            page_count=30,
            research=sample_research,
            custom_outline="",
        )

        sent_prompt = mock_llm.calls[0]["messages"][0].content
        assert "ПОЛЬЗОВАТЕЛЬСКИЙ ПЛАН" not in sent_prompt

    async def test_source_summary_formatting(
        self, outliner: Outliner
    ) -> None:
        research = ResearchResult(
            original_topic="Test",
            sources=[
                Source(url="https://a.com", title="Source A", snippet="Snippet A"),
                Source(url="https://b.com", title="Source B", snippet=""),
                Source(url="https://c.com", title="Source C", full_text="Full text C"),
            ],
        )

        summary = outliner._summarize_sources(research)
        assert "Source A" in summary
        assert "Snippet A" in summary
        assert "Source C" in summary
