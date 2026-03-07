"""Tests for section-by-section content writing."""

import pytest

from backend.app.pipeline.writer.section_writer import SectionWriter
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import Outline, OutlineChapter, SectionContent, Source


@pytest.fixture
def outline() -> Outline:
    return Outline(
        title="Цифровизация в управлении персоналом",
        introduction_points=["Актуальность", "Цель и задачи"],
        chapters=[
            OutlineChapter(
                number=1,
                title="Теоретические основы цифровизации",
                subsections=["1.1 Понятие цифровизации", "1.2 Методы оценки"],
                description="Обзор литературы",
                estimated_pages=8,
            ),
            OutlineChapter(
                number=2,
                title="Практическое применение",
                subsections=["2.1 Анализ рынка"],
                description="Практика",
                estimated_pages=10,
            ),
        ],
        conclusion_points=["Основные выводы", "Рекомендации"],
    )


@pytest.fixture
def sources() -> list[Source]:
    return [
        Source(
            url="https://example.com/1",
            title="Источник 1",
            snippet="Краткое описание",
            full_text="Полный текст источника номер один о цифровизации. " * 20,
            relevance_score=0.9,
        ),
        Source(
            url="https://example.com/2",
            title="Источник 2",
            snippet="Другой источник",
            full_text="Информация об управлении персоналом в цифровую эпоху. " * 15,
            relevance_score=0.8,
        ),
    ]


class TestSectionWriter:
    async def test_write_introduction(
        self, mock_llm: MockLLMProvider, outline: Outline
    ) -> None:
        intro_text = (
            "Актуальность данной темы обусловлена стремительным развитием "
            "цифровых технологий в сфере управления персоналом. "
            "Цель исследования — изучить влияние цифровизации."
        )
        mock_llm.set_responses([intro_text])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_introduction(
            topic="Цифровизация в HR",
            discipline="Менеджмент",
            outline=outline,
        )

        assert isinstance(result, SectionContent)
        assert result.chapter_number == 0
        assert result.section_title == "Введение"
        assert result.word_count > 0
        assert result.content == intro_text
        assert mock_llm.calls[0]["temperature"] == 0.6

    async def test_write_introduction_no_discipline(
        self, mock_llm: MockLLMProvider, outline: Outline
    ) -> None:
        mock_llm.set_responses(["Введение к курсовой работе."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_introduction(
            topic="Тема",
            discipline="",
            outline=outline,
        )

        prompt_content = mock_llm.calls[0]["messages"][0].content
        assert "не указана" in prompt_content

    async def test_write_section(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        section_text = (
            "Цифровизация представляет собой процесс внедрения [1] "
            "цифровых технологий. По данным исследований [2], "
            "это затрагивает все сферы деятельности."
        )
        mock_llm.set_responses([section_text])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_section(
            paper_title="Цифровизация в HR",
            chapter=outline.chapters[0],
            section_title="1.1 Понятие цифровизации",
            sources=sources,
            previous_sections=[],
        )

        assert result.chapter_number == 1
        assert result.section_title == "1.1 Понятие цифровизации"
        assert "1" in result.citations
        assert "2" in result.citations
        assert result.word_count > 0
        assert mock_llm.calls[0]["temperature"] == 0.7

    async def test_write_section_with_previous_context(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        previous = [
            SectionContent(
                chapter_number=1,
                section_title="1.1 Первый раздел",
                content="Предыдущий контент " * 50,
                word_count=100,
            ),
        ]
        mock_llm.set_responses(["Новый раздел."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_section(
            paper_title="Тема",
            chapter=outline.chapters[0],
            section_title="1.2 Второй раздел",
            sources=sources,
            previous_sections=previous,
        )

        prompt_content = mock_llm.calls[0]["messages"][0].content
        assert "1.1 Первый раздел" in prompt_content

    async def test_write_section_with_additional_instructions(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        mock_llm.set_responses(["Раздел с учётом инструкций."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_section(
            paper_title="Тема",
            chapter=outline.chapters[0],
            section_title="1.1 Раздел",
            sources=sources,
            previous_sections=[],
            additional_instructions="Включить статистику за 2024 год",
        )

        prompt_content = mock_llm.calls[0]["messages"][0].content
        assert "Включить статистику за 2024 год" in prompt_content

    async def test_write_conclusion(
        self, mock_llm: MockLLMProvider, outline: Outline
    ) -> None:
        conclusion_text = (
            "В ходе исследования были получены следующие результаты. "
            "Основные выводы подтверждают значимость цифровизации."
        )
        mock_llm.set_responses([conclusion_text])
        writer = SectionWriter(llm=mock_llm)

        sections = [
            SectionContent(
                chapter_number=1,
                section_title="1.1 Теория",
                content="Контент главы 1",
                word_count=500,
            ),
        ]

        result = await writer.write_conclusion(
            topic="Цифровизация",
            outline=outline,
            sections=sections,
        )

        assert result.chapter_number == 99
        assert result.section_title == "Заключение"
        assert result.word_count > 0
        assert mock_llm.calls[0]["temperature"] == 0.5

    async def test_write_section_no_citations(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        mock_llm.set_responses(["Текст без ссылок на источники."])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_section(
            paper_title="Тема",
            chapter=outline.chapters[0],
            section_title="1.1 Раздел",
            sources=sources,
            previous_sections=[],
        )

        assert result.citations == []

    async def test_format_previous_empty(self) -> None:
        result = SectionWriter._format_previous([])
        assert "первый раздел" in result.lower()

    async def test_format_sources_empty(self) -> None:
        result = SectionWriter._format_sources([])
        assert "не предоставлены" in result.lower()

    async def test_format_sources_truncates_to_8(self, sources: list[Source]) -> None:
        many_sources = sources * 10  # 20 sources
        result = SectionWriter._format_sources(many_sources)
        # Should only include first 8
        assert "[8]" in result
        assert "[9]" not in result
