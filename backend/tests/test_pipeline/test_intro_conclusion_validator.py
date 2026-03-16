"""Tests for introduction/conclusion structural validator."""

import pytest

from backend.app.pipeline.writer.intro_conclusion_validator import (
    IntroductionConclusionValidator,
)
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
        title="Цифровизация в HR",
        introduction_points=["Актуальность", "Цель"],
        chapters=[
            OutlineChapter(number=1, title="Теория", subsections=["1.1 Основы"]),
            OutlineChapter(number=2, title="Практика", subsections=["2.1 Анализ"]),
        ],
        conclusion_points=["Выводы"],
    )


@pytest.fixture
def complete_intro() -> SectionContent:
    return SectionContent(
        chapter_number=0,
        section_title="Введение",
        content=(
            "Актуальность данной темы обусловлена быстрым развитием технологий. "
            "Цель исследования — изучить влияние цифровизации на HR. "
            "Задачи исследования включают: проанализировать теорию, изучить практику. "
            "Объект исследования — управление персоналом. "
            "Предмет исследования — цифровые инструменты HR. "
            "Методы исследования: анализ литературы, сравнительный анализ. "
            "Структура работы: работа состоит из введения, двух глав и заключения."
        ),
        word_count=50,
    )


@pytest.fixture
def incomplete_intro() -> SectionContent:
    return SectionContent(
        chapter_number=0,
        section_title="Введение",
        content=(
            "Актуальность данной темы обусловлена быстрым развитием технологий. "
            "Цель исследования — изучить влияние цифровизации."
        ),
        word_count=15,
    )


@pytest.fixture
def good_conclusion() -> SectionContent:
    return SectionContent(
        chapter_number=99,
        section_title="Заключение",
        content=(
            "В ходе исследования получены следующие выводы и результаты. "
            "Практическая значимость работы заключается в разработке рекомендаций. "
            "Дальнейшие исследования могут быть направлены на углубление анализа."
        ),
        word_count=25,
    )


@pytest.fixture
def poor_conclusion() -> SectionContent:
    return SectionContent(
        chapter_number=99,
        section_title="Заключение",
        content="Таким образом, тема была рассмотрена в данной работе.",
        word_count=8,
    )


class TestIntroductionValidator:
    def test_complete_intro_has_no_missing(
        self, mock_llm: MockLLMProvider, complete_intro: SectionContent
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)
        missing = validator.check_introduction(complete_intro)
        assert missing == []

    def test_incomplete_intro_detects_missing(
        self, mock_llm: MockLLMProvider, incomplete_intro: SectionContent
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)
        missing = validator.check_introduction(incomplete_intro)

        assert "задачи" in missing
        assert "объект" in missing
        assert "предмет" in missing
        assert "методы" in missing
        assert "структура" in missing
        # These should be found
        assert "актуальность" not in missing
        assert "цель" not in missing

    def test_non_intro_section_returns_empty(
        self, mock_llm: MockLLMProvider
    ) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Раздел",
            content="Обычный раздел",
            word_count=2,
        )
        validator = IntroductionConclusionValidator(llm=mock_llm)
        missing = validator.check_introduction(section)
        assert missing == []

    async def test_fix_introduction(
        self,
        mock_llm: MockLLMProvider,
        incomplete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        fixed_text = (
            "Актуальность данной темы обусловлена быстрым развитием технологий. "
            "Цель исследования — изучить влияние цифровизации. "
            "Задачи исследования: проанализировать теорию, изучить практику. "
            "Объект исследования — управление персоналом. "
            "Предмет исследования — цифровые инструменты. "
            "Методы исследования: анализ литературы. "
            "Работа состоит из двух глав."
        )
        mock_llm.set_responses([fixed_text])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        missing = validator.check_introduction(incomplete_intro)
        result = await validator.fix_introduction(
            section=incomplete_intro,
            missing_elements=missing,
            topic="Цифровизация",
            discipline="Менеджмент",
            outline=outline,
        )

        assert result.chapter_number == 0
        assert result.word_count > incomplete_intro.word_count

    async def test_fix_no_missing_returns_original(
        self,
        mock_llm: MockLLMProvider,
        complete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)

        result = await validator.fix_introduction(
            section=complete_intro,
            missing_elements=[],
            topic="Тема",
            discipline="",
            outline=outline,
        )

        assert result.content == complete_intro.content
        assert len(mock_llm.calls) == 0


class TestConclusionValidator:
    def test_good_conclusion(
        self,
        mock_llm: MockLLMProvider,
        good_conclusion: SectionContent,
        complete_intro: SectionContent,
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)
        issues = validator.check_conclusion(good_conclusion, complete_intro)
        assert issues == []

    def test_poor_conclusion_detects_issues(
        self,
        mock_llm: MockLLMProvider,
        poor_conclusion: SectionContent,
        complete_intro: SectionContent,
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)
        issues = validator.check_conclusion(poor_conclusion, complete_intro)

        assert len(issues) >= 2
        assert any("практическ" in i.lower() or "значимост" in i.lower() for i in issues)
        assert any("дальнейш" in i.lower() or "перспектив" in i.lower() for i in issues)

    def test_non_conclusion_returns_empty(
        self, mock_llm: MockLLMProvider, complete_intro: SectionContent
    ) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1",
            content="Обычный текст",
            word_count=2,
        )
        validator = IntroductionConclusionValidator(llm=mock_llm)
        issues = validator.check_conclusion(section, complete_intro)
        assert issues == []

    async def test_fix_conclusion(
        self,
        mock_llm: MockLLMProvider,
        poor_conclusion: SectionContent,
        complete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        fixed_text = (
            "В ходе исследования получены следующие выводы и результаты работы. "
            "Практическая значимость работы состоит в применимости рекомендаций. "
            "Дальнейшие перспективы исследований связаны с расширением анализа."
        )
        mock_llm.set_responses([fixed_text])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        issues = validator.check_conclusion(poor_conclusion, complete_intro)
        result = await validator.fix_conclusion(
            section=poor_conclusion,
            issues=issues,
            topic="Цифровизация",
            discipline="Менеджмент",
            outline=outline,
        )

        assert result.chapter_number == 99
        assert result.section_title == "Заключение"
        assert result.word_count > poor_conclusion.word_count
        assert len(mock_llm.calls) == 1

    async def test_fix_no_issues_returns_original(
        self,
        mock_llm: MockLLMProvider,
        good_conclusion: SectionContent,
        complete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        validator = IntroductionConclusionValidator(llm=mock_llm)

        result = await validator.fix_conclusion(
            section=good_conclusion,
            issues=[],
            topic="Тема",
            discipline="",
            outline=outline,
        )

        assert result.content == good_conclusion.content
        assert len(mock_llm.calls) == 0

    async def test_fix_conclusion_empty_llm_response_returns_original(
        self,
        mock_llm: MockLLMProvider,
        poor_conclusion: SectionContent,
        complete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        mock_llm.set_responses([""])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        result = await validator.fix_conclusion(
            section=poor_conclusion,
            issues=["Отсутствуют формулировки выводов"],
            topic="Тема",
            discipline="Менеджмент",
            outline=outline,
        )

        assert result.content == poor_conclusion.content


@pytest.fixture
def sources() -> list[Source]:
    return [
        Source(
            url="https://example.com/1",
            title="Источник 1: Цифровизация HR",
            snippet="Краткое описание",
            full_text="Полный текст источника",
            relevance_score=0.9,
        ),
        Source(
            url="https://example.com/2",
            title="Источник 2: Управление персоналом",
            snippet="Другой источник",
            full_text="Информация об управлении",
            relevance_score=0.8,
        ),
    ]


class TestValidatorWithBibliography:
    """Tests that fix_introduction and fix_conclusion receive and use bibliography."""

    async def test_fix_introduction_includes_sources_in_prompt(
        self,
        mock_llm: MockLLMProvider,
        incomplete_intro: SectionContent,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """fix_introduction prompt should include bibliography sources."""
        bib = BibliographyRegistry.from_sources(sources)
        fixed_text = (
            "Актуальность данной темы [1] обусловлена развитием технологий. "
            "Цель исследования — изучить влияние [2]. "
            "Задачи исследования: проанализировать теорию. "
            "Объект исследования — управление персоналом. "
            "Предмет исследования — цифровые инструменты. "
            "Методы исследования: анализ литературы. "
            "Работа состоит из двух глав."
        )
        mock_llm.set_responses([fixed_text])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        missing = validator.check_introduction(incomplete_intro)
        result = await validator.fix_introduction(
            section=incomplete_intro,
            missing_elements=missing,
            topic="Цифровизация",
            discipline="Менеджмент",
            outline=outline,
            sources=sources,
            bibliography=bib,
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "РЕЕСТР ИСТОЧНИКОВ" in prompt
        assert "1" in result.citations
        assert "2" in result.citations

    async def test_fix_conclusion_includes_sources_in_prompt(
        self,
        mock_llm: MockLLMProvider,
        poor_conclusion: SectionContent,
        complete_intro: SectionContent,
        outline: Outline,
        sources: list[Source],
    ) -> None:
        """fix_conclusion prompt should include bibliography sources."""
        bib = BibliographyRegistry.from_sources(sources)
        fixed_text = (
            "В ходе исследования получены результаты [1]. "
            "Практическая значимость работы подтверждается данными [2]. "
            "Дальнейшие перспективы исследований связаны с расширением."
        )
        mock_llm.set_responses([fixed_text])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        issues = validator.check_conclusion(poor_conclusion, complete_intro)
        result = await validator.fix_conclusion(
            section=poor_conclusion,
            issues=issues,
            topic="Цифровизация",
            discipline="Менеджмент",
            outline=outline,
            sources=sources,
            bibliography=bib,
        )

        prompt = mock_llm.calls[0]["messages"][0].content
        assert "РЕЕСТР ИСТОЧНИКОВ" in prompt
        assert "1" in result.citations
        assert "2" in result.citations

    async def test_fix_introduction_without_bibliography(
        self,
        mock_llm: MockLLMProvider,
        incomplete_intro: SectionContent,
        outline: Outline,
    ) -> None:
        """fix_introduction should work without bibliography (backward compat)."""
        fixed_text = (
            "Актуальность обусловлена. Цель — изучить. "
            "Задачи: проанализировать. Объект — HR. "
            "Предмет — цифровые инструменты. "
            "Методы: анализ литературы. Работа состоит из глав."
        )
        mock_llm.set_responses([fixed_text])
        validator = IntroductionConclusionValidator(llm=mock_llm)

        missing = validator.check_introduction(incomplete_intro)
        result = await validator.fix_introduction(
            section=incomplete_intro,
            missing_elements=missing,
            topic="Тема",
            discipline="Менеджмент",
            outline=outline,
        )

        assert result.chapter_number == 0
        prompt = mock_llm.calls[0]["messages"][0].content
        assert "Источники не предоставлены" in prompt
