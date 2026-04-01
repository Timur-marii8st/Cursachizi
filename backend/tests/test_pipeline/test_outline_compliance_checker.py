"""Tests for OutlineComplianceChecker."""

import json

import pytest

from backend.app.pipeline.writer.outline_compliance_checker import OutlineComplianceChecker
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import Outline, OutlineChapter, SectionContent


@pytest.fixture
def checker(mock_llm: MockLLMProvider) -> OutlineComplianceChecker:
    return OutlineComplianceChecker(mock_llm)


@pytest.fixture
def sample_outline() -> Outline:
    return Outline(
        title="Тестовая курсовая",
        introduction_points=["Актуальность"],
        chapters=[
            OutlineChapter(
                number=1,
                title="Теоретические основы",
                subsections=["1.1 Понятие цифровизации", "1.2 Обзор литературы"],
                estimated_pages=10,
            ),
            OutlineChapter(
                number=2,
                title="Практический анализ",
                subsections=["2.1 Методология", "2.2 Результаты"],
                estimated_pages=10,
            ),
        ],
        conclusion_points=["Выводы"],
    )


@pytest.fixture
def matching_sections() -> list[SectionContent]:
    return [
        SectionContent(
            chapter_number=1,
            section_title="1.1 Понятие цифровизации",
            content="Цифровизация — это процесс внедрения цифровых технологий " * 50,
        ),
        SectionContent(
            chapter_number=1,
            section_title="1.2 Обзор литературы",
            content="В литературе рассматриваются различные подходы " * 50,
        ),
        SectionContent(
            chapter_number=2,
            section_title="2.1 Методология",
            content="Для исследования использовались методы анализа " * 50,
        ),
        SectionContent(
            chapter_number=2,
            section_title="2.2 Результаты",
            content="Результаты исследования показали значительные изменения " * 50,
        ),
    ]


class TestOutlineComplianceChecker:
    async def test_all_sections_compliant(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
        sample_outline: Outline,
        matching_sections: list[SectionContent],
    ) -> None:
        """When all sections are compliant, result should have no issues."""
        compliant_response = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        mock_llm.set_responses([compliant_response] * 4)

        result = await checker.check(sample_outline, matching_sections)

        assert result.is_compliant
        assert len(result.issues) == 0
        assert result.sections_checked == 4
        assert result.sections_compliant == 4

    async def test_missing_section_detected(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
        sample_outline: Outline,
    ) -> None:
        """If a section from the outline has no written content, issue is raised."""
        # Only provide 3 of 4 sections
        sections = [
            SectionContent(
                chapter_number=1,
                section_title="1.1 Понятие цифровизации",
                content="Текст " * 100,
            ),
            SectionContent(
                chapter_number=1,
                section_title="1.2 Обзор литературы",
                content="Текст " * 100,
            ),
            SectionContent(
                chapter_number=2,
                section_title="2.1 Методология",
                content="Текст " * 100,
            ),
            # Missing: 2.2 Результаты
        ]

        compliant_response = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        mock_llm.set_responses([compliant_response] * 3)

        result = await checker.check(sample_outline, sections)

        assert not result.is_compliant
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "missing_content"
        assert "Результаты" in result.issues[0].description

    async def test_off_topic_section_detected(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
        sample_outline: Outline,
        matching_sections: list[SectionContent],
    ) -> None:
        """When LLM detects off-topic content, a compliance issue is created."""
        compliant = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        off_topic = json.dumps({
            "is_compliant": False,
            "issue_type": "off_topic",
            "description": "Раздел описывает маркетинг вместо цифровизации",
            "suggestion": "Переписать с фокусом на цифровизацию",
            "missing_topics": ["цифровые технологии"],
        })
        mock_llm.set_responses([off_topic, compliant, compliant, compliant])

        result = await checker.check(sample_outline, matching_sections)

        assert not result.is_compliant
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "off_topic"
        assert result.sections_checked == 4
        assert result.sections_compliant == 3

    async def test_llm_parse_error_becomes_validation_issue(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
        sample_outline: Outline,
        matching_sections: list[SectionContent],
    ) -> None:
        """If LLM returns invalid JSON, surface a validation issue instead of a silent pass."""
        compliant = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        mock_llm.set_responses(["not json at all", compliant, compliant, compliant])

        result = await checker.check(sample_outline, matching_sections)

        assert not result.is_compliant
        assert result.sections_checked == 4
        assert result.issues[0].issue_type == "validation_error"

    async def test_fuzzy_matching_by_partial_title(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
    ) -> None:
        """Sections with slightly different titles should still match."""
        outline = Outline(
            title="Тест",
            introduction_points=[],
            chapters=[
                OutlineChapter(
                    number=1,
                    title="Глава 1",
                    subsections=["1.1 Понятие цифровизации HR"],
                    estimated_pages=10,
                ),
            ],
            conclusion_points=[],
        )
        # Written title is a substring of outline title
        sections = [
            SectionContent(
                chapter_number=1,
                section_title="Понятие цифровизации HR",
                content="Текст " * 100,
            ),
        ]
        compliant = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        mock_llm.set_responses([compliant])

        result = await checker.check(outline, sections)
        assert result.is_compliant

    async def test_chapter_without_subsections(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
    ) -> None:
        """Chapters without subsections use chapter title as section title."""
        outline = Outline(
            title="Тест",
            introduction_points=[],
            chapters=[
                OutlineChapter(
                    number=1,
                    title="Обзор литературы",
                    subsections=[],
                    estimated_pages=10,
                ),
            ],
            conclusion_points=[],
        )
        sections = [
            SectionContent(
                chapter_number=1,
                section_title="Обзор литературы",
                content="Текст " * 100,
            ),
        ]
        compliant = json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        })
        mock_llm.set_responses([compliant])

        result = await checker.check(outline, sections)
        assert result.is_compliant
        assert result.sections_checked == 1

    async def test_json_in_code_block_parsed(
        self,
        checker: OutlineComplianceChecker,
        mock_llm: MockLLMProvider,
        sample_outline: Outline,
        matching_sections: list[SectionContent],
    ) -> None:
        """LLM wrapping JSON in ```json ... ``` should still be parsed."""
        wrapped = "```json\n" + json.dumps({
            "is_compliant": True,
            "issue_type": "none",
            "description": "",
            "suggestion": "",
            "missing_topics": [],
        }) + "\n```"
        mock_llm.set_responses([wrapped] * 4)

        result = await checker.check(sample_outline, matching_sections)
        assert result.is_compliant


class TestFindSection:
    def test_exact_match(self) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Основы",
            content="text",
        )
        section_map = {(1, "1.1 Основы"): section}
        found = OutlineComplianceChecker._find_section(section_map, 1, "1.1 Основы")
        assert found is section

    def test_partial_title_match(self) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Основные понятия цифровизации",
            content="text",
        )
        section_map = {(1, "1.1 Основные понятия цифровизации"): section}
        found = OutlineComplianceChecker._find_section(
            section_map, 1, "Основные понятия цифровизации"
        )
        assert found is section

    def test_numbering_stripped_match(self) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1. Понятие валюты",
            content="text",
        )
        section_map = {(1, "1.1. Понятие валюты"): section}
        found = OutlineComplianceChecker._find_section(
            section_map, 1, "1.1 Понятие валюты"
        )
        assert found is section

    def test_wrong_chapter_no_match(self) -> None:
        section = SectionContent(
            chapter_number=1,
            section_title="1.1 Основы",
            content="text",
        )
        section_map = {(1, "1.1 Основы"): section}
        found = OutlineComplianceChecker._find_section(section_map, 2, "1.1 Основы")
        assert found is None

    def test_no_match_returns_none(self) -> None:
        section_map: dict = {}
        found = OutlineComplianceChecker._find_section(section_map, 1, "Несуществующий")
        assert found is None
