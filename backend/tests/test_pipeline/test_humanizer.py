"""Tests for humanizer (translation cycling + LLM cleanup)."""

import pytest

from backend.app.pipeline.writer.humanizer import Humanizer, TranslationProvider
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import SectionContent


class MockTranslationProvider(TranslationProvider):
    """Mock translation provider for testing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        self.calls.append((source_lang, target_lang, text[:50]))
        # Simulate translation by adding a marker
        return f"[translated:{source_lang}→{target_lang}] {text}"


class FailingTranslationProvider(TranslationProvider):
    """Translation provider that always fails."""

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        raise ConnectionError("Translation API unavailable")


@pytest.fixture
def mock_translator() -> MockTranslationProvider:
    return MockTranslationProvider()


@pytest.fixture
def body_section() -> SectionContent:
    return SectionContent(
        chapter_number=1,
        section_title="1.1 Теоретические основы",
        content=(
            "Цифровизация представляет собой процесс внедрения цифровых "
            "технологий [1]. По мнению исследователей [2], это затрагивает "
            "все сферы деятельности."
        ),
        citations=["1", "2"],
        word_count=20,
    )


class TestHumanizer:
    async def test_humanize_section(
        self,
        mock_llm: MockLLMProvider,
        mock_translator: MockTranslationProvider,
        body_section: SectionContent,
    ) -> None:
        mock_llm.set_responses([
            "Процесс цифровизации охватывает внедрение технологий [1]. "
            "Исследователи подтверждают [2] широту влияния."
        ])
        humanizer = Humanizer(llm=mock_llm, translator=mock_translator)

        result = await humanizer.humanize_section(body_section)

        assert result.chapter_number == 1
        assert result.section_title == "1.1 Теоретические основы"
        assert "1" in result.citations
        assert "2" in result.citations
        # Translation chain: ru→en, en→de, de→ru
        assert len(mock_translator.calls) == 3
        assert mock_translator.calls[0][0] == "ru"
        assert mock_translator.calls[0][1] == "en"
        assert mock_translator.calls[2][1] == "ru"

    async def test_humanize_all_skips_intro_and_conclusion(
        self,
        mock_llm: MockLLMProvider,
        mock_translator: MockTranslationProvider,
    ) -> None:
        sections = [
            SectionContent(
                chapter_number=0,
                section_title="Введение",
                content="Текст введения.",
                word_count=2,
            ),
            SectionContent(
                chapter_number=1,
                section_title="1.1 Раздел",
                content="Текст раздела [1].",
                citations=["1"],
                word_count=3,
            ),
            SectionContent(
                chapter_number=99,
                section_title="Заключение",
                content="Текст заключения.",
                word_count=2,
            ),
        ]
        mock_llm.set_responses(["Обработанный текст раздела [1]."])
        humanizer = Humanizer(llm=mock_llm, translator=mock_translator)

        result = await humanizer.humanize_all(sections)

        assert len(result) == 3
        # Intro unchanged
        assert result[0].content == "Текст введения."
        # Body section was processed
        assert result[1].content != "Текст раздела [1]."
        # Conclusion unchanged
        assert result[2].content == "Текст заключения."
        # Only 1 LLM call (for body section)
        assert len(mock_llm.calls) == 1

    async def test_translation_failure_returns_original(
        self,
        mock_llm: MockLLMProvider,
        body_section: SectionContent,
    ) -> None:
        failing = FailingTranslationProvider()
        humanizer = Humanizer(llm=mock_llm, translator=failing)

        result = await humanizer.humanize_section(body_section)

        # Should return original section on translation failure
        assert result.content == body_section.content
        assert len(mock_llm.calls) == 0  # LLM cleanup never called

    async def test_custom_language_chain(
        self,
        mock_llm: MockLLMProvider,
        mock_translator: MockTranslationProvider,
        body_section: SectionContent,
    ) -> None:
        mock_llm.set_responses(["Результат."])
        humanizer = Humanizer(
            llm=mock_llm,
            translator=mock_translator,
            language_chain=["ru", "fr", "en", "ru"],
        )

        await humanizer.humanize_section(body_section)

        assert len(mock_translator.calls) == 3
        assert mock_translator.calls[0] == ("ru", "fr", body_section.content[:50])
        assert mock_translator.calls[1][0] == "fr"
        assert mock_translator.calls[1][1] == "en"
        assert mock_translator.calls[2][1] == "ru"

    async def test_empty_llm_response_returns_original(
        self,
        mock_llm: MockLLMProvider,
        mock_translator: MockTranslationProvider,
        body_section: SectionContent,
    ) -> None:
        mock_llm.set_responses([""])
        humanizer = Humanizer(llm=mock_llm, translator=mock_translator)

        result = await humanizer.humanize_section(body_section)

        assert result.content == body_section.content
