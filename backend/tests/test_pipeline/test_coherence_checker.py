"""Tests for cross-section coherence checker."""

import json

import pytest

from backend.app.pipeline.writer.coherence_checker import CoherenceChecker
from backend.app.testing import MockLLMProvider
from shared.schemas.pipeline import CoherenceResult, SectionContent


@pytest.fixture
def sections() -> list[SectionContent]:
    return [
        SectionContent(
            chapter_number=1,
            section_title="1.1 Понятие цифровизации",
            content=(
                "Цифровизация представляет собой процесс внедрения цифровых "
                "технологий в деятельность организации [1]. По мнению ряда "
                "авторов, цифровая трансформация является ключевым фактором "
                "конкурентоспособности [2]."
            ),
            citations=["1", "2"],
            word_count=30,
        ),
        SectionContent(
            chapter_number=1,
            section_title="1.2 Методы оценки цифровизации",
            content=(
                "Для оценки уровня цифровой трансформации используются "
                "различные методики. Индекс цифровизации позволяет "
                "количественно измерить степень внедрения технологий [3]."
            ),
            citations=["3"],
            word_count=25,
        ),
        SectionContent(
            chapter_number=2,
            section_title="2.1 Анализ практики",
            content=(
                "Практический анализ показывает, что компании, активно "
                "использующие цифровые инструменты, демонстрируют более "
                "высокие показатели эффективности [4]."
            ),
            citations=["4"],
            word_count=20,
        ),
    ]


class TestCoherenceChecker:
    async def test_check_no_issues(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        mock_llm.set_responses([json.dumps({"issues": []})])
        checker = CoherenceChecker(llm=mock_llm)

        result = await checker.check(sections)

        assert isinstance(result, CoherenceResult)
        assert result.issues_found == 0
        assert result.issues == []

    async def test_check_finds_issues(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        issues_response = json.dumps({
            "issues": [
                {
                    "issue_type": "terminology",
                    "description": "В разделе 1.1 используется 'цифровизация', а в 2.1 — 'цифровые инструменты'",
                    "section_a": "1.1 Понятие цифровизации",
                    "section_b": "2.1 Анализ практики",
                    "suggestion": "Унифицировать терминологию",
                },
                {
                    "issue_type": "missing_reference",
                    "description": "В разделе 2.1 нет ссылки на теоретические основы из Главы 1",
                    "section_a": "2.1 Анализ практики",
                    "section_b": "",
                    "suggestion": "Добавить 'как было показано в Главе 1...'",
                },
            ]
        })
        mock_llm.set_responses([issues_response])
        checker = CoherenceChecker(llm=mock_llm)

        result = await checker.check(sections)

        assert result.issues_found == 2
        assert result.issues[0].issue_type == "terminology"
        assert result.issues[1].issue_type == "missing_reference"

    async def test_check_skips_single_section(
        self, mock_llm: MockLLMProvider
    ) -> None:
        single = [SectionContent(
            chapter_number=1,
            section_title="1.1 Единственный",
            content="Текст",
            word_count=1,
        )]
        checker = CoherenceChecker(llm=mock_llm)

        result = await checker.check(single)

        assert result.issues_found == 0
        assert len(mock_llm.calls) == 0  # No LLM call made

    async def test_fix_applies_corrections(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        # First call: check returns issues
        # Second call: fix for section 2.1
        mock_llm.set_responses([
            json.dumps({
                "issues": [{
                    "issue_type": "missing_reference",
                    "description": "Нет ссылки на Главу 1",
                    "section_a": "2.1 Анализ практики",
                    "section_b": "",
                    "suggestion": "Добавить ссылку",
                }]
            }),
            "Как было показано в Главе 1, цифровизация является ключевым фактором. "
            "Практический анализ подтверждает эти выводы [4].",
        ])
        checker = CoherenceChecker(llm=mock_llm)

        check_result = await checker.check(sections)
        updated_sections, fix_result = await checker.fix(
            sections=sections,
            coherence_result=check_result,
        )

        assert fix_result.fixes_applied == 1
        assert "2.1 Анализ практики" in fix_result.sections_modified
        assert "Как было показано" in updated_sections[2].content

    async def test_fix_no_issues_returns_original(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        checker = CoherenceChecker(llm=mock_llm)
        empty_result = CoherenceResult()

        updated, result = await checker.fix(sections, empty_result)

        assert updated == sections
        assert result.fixes_applied == 0

    async def test_parse_malformed_json(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        mock_llm.set_responses(["This is not valid JSON"])
        checker = CoherenceChecker(llm=mock_llm)

        result = await checker.check(sections)

        assert result.issues_found == 0

    async def test_parse_json_in_code_block(
        self, mock_llm: MockLLMProvider, sections: list[SectionContent]
    ) -> None:
        response = '```json\n{"issues": [{"issue_type": "logic_gap", "description": "Нет перехода", "section_a": "1.1", "section_b": "1.2", "suggestion": "Добавить"}]}\n```'
        mock_llm.set_responses([response])
        checker = CoherenceChecker(llm=mock_llm)

        result = await checker.check(sections)

        assert result.issues_found == 1
