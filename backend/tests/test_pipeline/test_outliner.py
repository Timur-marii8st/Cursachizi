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
