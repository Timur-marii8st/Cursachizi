"""Tests for section-by-section content writing."""

import pytest

from backend.app.pipeline.writer.section_writer import SectionWriter, _safe
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import (
    BibliographyRegistry,
    Outline,
    OutlineChapter,
    SectionContent,
    Source,
)


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

    async def test_safe_escapes_curly_braces(self) -> None:
        """SEC-003: curly braces in user input must be escaped to prevent KeyError."""
        assert _safe("topic {foo} bar") == "topic {{foo}} bar"
        assert _safe("{paper_title}") == "{{paper_title}}"
        assert _safe("normal text") == "normal text"
        assert _safe("") == ""

    async def test_format_string_injection_does_not_raise(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """SEC-003: topic containing {unknown_var} must not raise KeyError."""
        mock_llm.set_responses(["Раздел написан успешно."])
        writer = SectionWriter(llm=mock_llm)

        # This would previously raise KeyError: 'unknown_var'
        await writer.write_introduction(
            topic="Тема {unknown_var} исследования",
            discipline="Менеджмент {discipline}",
            outline=outline,
        )
        # Verify the literal text reached the LLM prompt (braces doubled)
        prompt = mock_llm.calls[0]["messages"][0].content
        assert "Тема {unknown_var} исследования" in prompt or "{{unknown_var}}" in prompt

    async def test_format_string_injection_in_section(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """SEC-003: additional_instructions with braces must not crash write_section."""
        mock_llm.set_responses(["Результат."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_section(
            paper_title="Тема {paper_title}",
            chapter=outline.chapters[0],
            section_title="1.1 Раздел {section_title}",
            sources=sources,
            previous_sections=[],
            additional_instructions="Включить {данные} за 2024",
        )
        prompt = mock_llm.calls[0]["messages"][0].content
        assert "Включить" in prompt


class TestSectionWriterEmptySources:
    """Tests for section writing when no sources are available."""

    async def test_empty_bibliography_prevents_citation_hallucination(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
    ) -> None:
        """When bibliography is empty and sources are empty,
        prompt should instruct LLM not to use citations."""
        mock_llm.set_responses(["Текст раздела без цитирования."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_section(
            paper_title="Тестовая тема",
            chapter=outline.chapters[0],
            section_title="1.1 Раздел",
            sources=[],
            previous_sections=[],
            bibliography=BibliographyRegistry(entries=[]),
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "НЕ используй ссылки [N]" in prompt
        assert "Источники не предоставлены" in prompt

    async def test_with_sources_includes_citation_instructions(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """When bibliography has entries, normal citation instructions apply."""
        bib = BibliographyRegistry.from_sources(sources)
        mock_llm.set_responses(["Текст с цитированием [1]."])
        writer = SectionWriter(llm=mock_llm)

        await writer.write_section(
            paper_title="Тестовая тема",
            chapter=outline.chapters[0],
            section_title="1.1 Раздел",
            sources=sources,
            previous_sections=[],
            bibliography=bib,
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "НЕ используй ссылки [N]" not in prompt
        assert "Источник 1" in prompt


class TestIntroductionWithBibliography:
    """Tests that introduction receives and uses bibliography sources."""

    async def test_introduction_receives_bibliography(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """Introduction prompt should include bibliography sources."""
        bib = BibliographyRegistry.from_sources(sources)
        mock_llm.set_responses([
            "Актуальность темы [1] подтверждается исследованиями [2]."
        ])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_introduction(
            topic="Цифровизация в HR",
            discipline="Менеджмент",
            outline=outline,
            sources=sources,
            bibliography=bib,
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "РЕЕСТР ИСТОЧНИКОВ" in prompt
        assert "Источник 1" in prompt or "[1]" in prompt
        assert result.citations == ["1", "2"] or set(result.citations) == {"1", "2"}

    async def test_introduction_without_sources_warns_no_citations(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
    ) -> None:
        """Introduction without sources should tell LLM not to use citations."""
        mock_llm.set_responses(["Актуальность темы обусловлена развитием."])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_introduction(
            topic="Тема",
            discipline="Менеджмент",
            outline=outline,
            sources=[],
            bibliography=BibliographyRegistry(entries=[]),
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "НЕ используй ссылки [N]" in prompt
        assert result.citations == []

    async def test_introduction_extracts_citations(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """Introduction should extract citation numbers from generated text."""
        bib = BibliographyRegistry.from_sources(sources)
        mock_llm.set_responses([
            "Исследования показывают [1], что тема актуальна [2]. "
            "Также подтверждается [1] другими работами."
        ])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_introduction(
            topic="Тема",
            discipline="Дисциплина",
            outline=outline,
            sources=sources,
            bibliography=bib,
        )

        assert "1" in result.citations
        assert "2" in result.citations


class TestConclusionWithBibliography:
    """Tests that conclusion receives and uses bibliography sources."""

    async def test_conclusion_receives_bibliography(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """Conclusion prompt should include bibliography sources."""
        bib = BibliographyRegistry.from_sources(sources)
        mock_llm.set_responses([
            "Результаты подтверждают данные [1]. Выводы согласуются с [2]."
        ])
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
            sources=sources,
            bibliography=bib,
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "РЕЕСТР ИСТОЧНИКОВ" in prompt
        assert result.citations == ["1", "2"] or set(result.citations) == {"1", "2"}

    async def test_conclusion_extracts_citations(
        self,
        mock_llm: MockLLMProvider,
        outline: Outline,
    ) -> None:
        """Conclusion should extract citation numbers from generated text."""
        mock_llm.set_responses([
            "Исследование подтвердило [3] основные выводы."
        ])
        writer = SectionWriter(llm=mock_llm)

        result = await writer.write_conclusion(
            topic="Тема",
            outline=outline,
            sections=[],
        )

        assert "3" in result.citations
