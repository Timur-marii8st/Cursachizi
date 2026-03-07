"""Tests for section quality evaluator and rewriter."""

import pytest

from backend.app.pipeline.writer.section_evaluator import SectionEvaluator
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import (
    OutlineChapter,
    SectionContent,
    SectionEvaluation,
    Source,
)


@pytest.fixture
def chapter() -> OutlineChapter:
    return OutlineChapter(
        number=1,
        title="Теоретические основы",
        subsections=["1.1 Понятие цифровизации"],
        description="Обзор литературы",
        estimated_pages=8,
    )


@pytest.fixture
def sources() -> list[Source]:
    return [
        Source(
            url="https://example.com/1",
            title="Источник 1",
            snippet="Краткое описание",
            full_text="Полный текст об управлении персоналом. " * 20,
            relevance_score=0.9,
        ),
    ]


class TestSectionEvaluator:
    def test_passing_section(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Раздел",
            content="Текст раздела [1] с цитатами [2]. " * 100,
            citations=["1", "2"],
            word_count=700,
        )

        result = evaluator.evaluate(section, target_words=1000, min_citations=2)

        assert result.passed is True
        assert result.word_count_ok is True
        assert result.citations_ok is True
        assert result.no_duplication is True

    def test_too_short_section(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Раздел",
            content="Короткий текст [1] [2].",
            citations=["1", "2"],
            word_count=3,
        )

        result = evaluator.evaluate(section, target_words=1000, min_citations=2)

        assert result.passed is False
        assert result.word_count_ok is False
        assert "слов" in result.feedback.lower()

    def test_no_citations(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Раздел",
            content="Текст без ссылок на источники. " * 100,
            citations=[],
            word_count=700,
        )

        result = evaluator.evaluate(section, target_words=1000, min_citations=2)

        assert result.passed is False
        assert result.citations_ok is False
        assert "ссылок" in result.feedback.lower()

    def test_intro_skips_citation_check(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        section = SectionContent(
            chapter_number=0,
            section_title="Введение",
            content="Введение без цитат. " * 100,
            citations=[],
            word_count=700,
        )

        result = evaluator.evaluate(section, target_words=1000, min_citations=2)

        assert result.citations_ok is True

    def test_conclusion_skips_citation_check(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        section = SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content="Заключение без цитат. " * 100,
            citations=[],
            word_count=700,
        )

        result = evaluator.evaluate(section, target_words=1000, min_citations=2)

        assert result.citations_ok is True

    def test_duplication_detected(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        shared_text = "Цифровизация представляет собой процесс внедрения цифровых технологий. " * 50

        section = SectionContent(
            chapter_number=1,
            section_title="1.2 Второй раздел",
            content=shared_text + " Дополнение [1] [2].",
            citations=["1", "2"],
            word_count=600,
        )
        previous = [SectionContent(
            chapter_number=1,
            section_title="1.1 Первый раздел",
            content=shared_text,
            citations=["1"],
            word_count=500,
        )]

        result = evaluator.evaluate(
            section, target_words=1000, min_citations=2, previous_sections=previous
        )

        assert result.no_duplication is False
        assert "пересечение" in result.feedback.lower()

    async def test_rewrite(
        self,
        mock_llm: MockLLMProvider,
        chapter: OutlineChapter,
        sources: list[Source],
    ) -> None:
        mock_llm.set_responses([
            "Расширенный текст раздела с цитатами [1] и ссылками [2]. "
            "Дополнительный контент для достижения нужного объёма. " * 20
        ])
        evaluator = SectionEvaluator(llm=mock_llm)

        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Раздел",
            content="Короткий текст.",
            citations=[],
            word_count=2,
        )
        evaluation = SectionEvaluation(
            section_title="1.1 Раздел",
            passed=False,
            word_count_ok=False,
            citations_ok=False,
            feedback="- Слишком мало слов\n- Нет цитат",
        )

        rewritten = await evaluator.rewrite(
            section=section,
            evaluation=evaluation,
            chapter=chapter,
            sources=sources,
            target_words=1000,
        )

        assert rewritten.word_count > section.word_count
        assert len(rewritten.citations) > 0
        assert "1" in rewritten.citations

    def test_overlap_calculation(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)

        text_a = "один два три четыре пять шесть семь восемь"
        text_b = "один два три четыре пять шесть семь восемь"
        assert evaluator._calculate_overlap(text_a, text_b) == 1.0

        text_c = "совершенно другой текст совершенно другие слова"
        assert evaluator._calculate_overlap(text_a, text_c) == 0.0

    def test_overlap_empty_text(self, mock_llm: MockLLMProvider) -> None:
        evaluator = SectionEvaluator(llm=mock_llm)
        assert evaluator._calculate_overlap("", "текст") == 0.0
        assert evaluator._calculate_overlap("", "") == 0.0
