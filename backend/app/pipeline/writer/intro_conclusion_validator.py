"""Introduction and conclusion structural validator.

Checks that all required GOST elements are present in the introduction
and that conclusion addresses all tasks from the introduction.
"""

import re

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import BibliographyRegistry, Outline, SectionContent, Source

logger = structlog.get_logger()

# Required elements in a GOST-compliant introduction
REQUIRED_INTRO_ELEMENTS = {
    "актуальность": [
        r"актуальн",
    ],
    "цель": [
        r"цель\s+(исследования|работы|данн)",
        r"целью\s+(исследования|работы|данн)",
    ],
    "задачи": [
        r"задач[иа]\s+(исследования|работы|данн)",
    ],
    "объект": [
        r"объект\s+(исследования|изучения)",
        r"объектом\s+(исследования|изучения)",
    ],
    "предмет": [
        r"предмет\s+(исследования|изучения)",
        r"предметом\s+(исследования|изучения)",
    ],
    "методы": [
        r"метод[ыа]\s+(исследования|работы)",
        r"методологическ",
        r"методическ",
    ],
    "структура": [
        r"структур[аы]\s+(работы|курсовой|исследования)",
        r"работа\s+состоит",
        r"состоит\s+из",
    ],
}

CONCLUSION_FIX_PROMPT = """Ты — опытный автор научных работ на русском языке. Доработай заключение курсовой работы, устранив выявленные недостатки.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}

ТЕКУЩЕЕ ЗАКЛЮЧЕНИЕ:
{current_text}

ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ:
{issues}

СТРУКТУРА РАБОТЫ:
{outline_summary}

РЕЕСТР ИСТОЧНИКОВ (при необходимости ссылайся по номерам [N]):
{sources_text}

ТРЕБОВАНИЯ:
1. Устрани ТОЛЬКО указанные проблемы, органично встроив новые фрагменты в текст
2. Сохрани существующий текст максимально без изменений
3. Академический стиль (третье лицо, безличные конструкции)
4. Каждый новый блок — отдельный абзац
5. Сохрани все существующие ссылки [N] на источники
6. НЕ выдумывай свои источники — используй ТОЛЬКО номера из реестра

Напиши ТОЛЬКО полный текст заключения с исправленными недостатками."""

INTRO_FIX_PROMPT = """Ты — опытный автор научных работ на русском языке. Дополни введение курсовой работы недостающими элементами.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}

ТЕКУЩЕЕ ВВЕДЕНИЕ:
{current_text}

НЕДОСТАЮЩИЕ ОБЯЗАТЕЛЬНЫЕ ЭЛЕМЕНТЫ:
{missing_elements}

СТРУКТУРА РАБОТЫ:
{outline_summary}

РЕЕСТР ИСТОЧНИКОВ (используй для ссылок в формате [N]):
{sources_text}

ТРЕБОВАНИЯ:
1. Добавь ТОЛЬКО недостающие элементы, органично встроив их в текст
2. Сохрани существующий текст максимально без изменений
3. Академический стиль (третье лицо, безличные конструкции)
4. Каждый новый элемент — отдельный абзац или логический блок
5. Сохрани все существующие ссылки [N] на источники
6. При добавлении раздела «степень разработанности» используй ссылки [N] из реестра источников
7. НЕ выдумывай свои источники — используй ТОЛЬКО номера из реестра

Напиши ТОЛЬКО полный текст введения с добавленными элементами."""


class IntroductionConclusionValidator:
    """Validates structural completeness of introduction and conclusion."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def check_introduction(self, section: SectionContent) -> list[str]:
        """Check which required GOST elements are missing from introduction.

        Returns list of missing element names.
        """
        if section.chapter_number != 0:
            return []

        text = section.content.lower()
        missing = []

        for element_name, patterns in REQUIRED_INTRO_ELEMENTS.items():
            found = any(re.search(pattern, text) for pattern in patterns)
            if not found:
                missing.append(element_name)

        if missing:
            logger.info("intro_missing_elements", missing=missing)

        return missing

    async def fix_introduction(
        self,
        section: SectionContent,
        missing_elements: list[str],
        topic: str,
        discipline: str,
        outline: Outline,
        model: str | None = None,
        sources: list[Source] | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Regenerate introduction to include missing elements."""
        if not missing_elements:
            return section

        element_descriptions = {
            "актуальность": "Актуальность темы исследования (1-2 абзаца, почему тема важна сейчас)",
            "цель": "Цель исследования (1 чёткое предложение)",
            "задачи": "Задачи исследования (3-5 задач, каждая начинается с глагола: изучить, проанализировать, определить...)",
            "объект": "Объект исследования (что изучается в широком смысле)",
            "предмет": "Предмет исследования (конкретный аспект объекта)",
            "методы": "Методы исследования (анализ литературы, сравнительный анализ, статистический анализ и т.д.)",
            "структура": "Структура работы (краткое описание содержания каждой главы)",
        }

        missing_text = "\n".join(
            f"- {element_descriptions.get(el, el)}"
            for el in missing_elements
        )

        outline_summary = "\n".join(
            f"Глава {ch.number}: {ch.title}" for ch in outline.chapters
        )

        # Build sources text for the prompt
        if bibliography and bibliography.entries:
            sources_text = bibliography.format_for_prompt()
        elif sources:
            sources_text = self._format_sources(sources)
        else:
            sources_text = "Источники не предоставлены."

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=INTRO_FIX_PROMPT.format(
                topic=topic,
                discipline=discipline or "не указана",
                current_text=section.content,
                missing_elements=missing_text,
                outline_summary=outline_summary,
                sources_text=sources_text,
            ))],
            model=model,
            temperature=0.5,
            max_tokens=3000,
        )

        fixed_content = response.content.strip()
        if not fixed_content:
            return section

        # Re-extract citations from the fixed content
        citations = list(set(re.findall(r"\[(\d+)\]", fixed_content)))
        logger.info(
            "intro_fixed",
            added_elements=missing_elements,
            old_words=section.word_count,
            new_words=len(fixed_content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=0,
            section_title="Введение",
            content=fixed_content,
            citations=citations,
            word_count=len(fixed_content.split()),
        )

    def check_conclusion(
        self, conclusion: SectionContent, introduction: SectionContent
    ) -> list[str]:
        """Check that conclusion addresses tasks mentioned in introduction.

        Returns list of issues found.
        """
        if conclusion.chapter_number != 99:
            return []

        issues = []
        conclusion_text = conclusion.content.lower()

        # Check for basic conclusion structure
        if "вывод" not in conclusion_text and "результат" not in conclusion_text:
            issues.append("Отсутствуют формулировки выводов")

        if "практическ" not in conclusion_text and "значимост" not in conclusion_text:
            issues.append("Не указана практическая значимость результатов")

        if "дальнейш" not in conclusion_text and "перспектив" not in conclusion_text:
            issues.append("Не обозначены направления дальнейших исследований")

        if issues:
            logger.info("conclusion_issues", issues=issues)

        return issues

    async def fix_conclusion(
        self,
        section: SectionContent,
        issues: list[str],
        topic: str,
        discipline: str,
        outline: Outline,
        model: str | None = None,
        sources: list[Source] | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Regenerate conclusion to fix detected structural issues."""
        if not issues:
            return section

        issue_descriptions = {
            "Отсутствуют формулировки выводов": (
                "Добавь явные выводы по каждой главе работы (ключевое слово «вывод» или «результат»)"
            ),
            "Не указана практическая значимость результатов": (
                "Добавь абзац о практической значимости полученных результатов"
            ),
            "Не обозначены направления дальнейших исследований": (
                "Добавь абзац о перспективах и направлениях дальнейших исследований"
            ),
        }

        issues_text = "\n".join(
            f"- {issue_descriptions.get(issue, issue)}"
            for issue in issues
        )

        outline_summary = "\n".join(
            f"Глава {ch.number}: {ch.title}" for ch in outline.chapters
        )

        # Build sources text for the prompt
        if bibliography and bibliography.entries:
            sources_text = bibliography.format_for_prompt()
        elif sources:
            sources_text = self._format_sources(sources)
        else:
            sources_text = "Источники не предоставлены."

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=CONCLUSION_FIX_PROMPT.format(
                topic=topic,
                discipline=discipline or "не указана",
                current_text=section.content,
                issues=issues_text,
                outline_summary=outline_summary,
                sources_text=sources_text,
            ))],
            model=model,
            temperature=0.5,
            max_tokens=3000,
        )

        fixed_content = response.content.strip()
        if not fixed_content:
            return section

        # Re-extract citations from the fixed content
        citations = list(set(re.findall(r"\[(\d+)\]", fixed_content)))
        logger.info(
            "conclusion_fixed",
            fixed_issues=issues,
            old_words=section.word_count,
            new_words=len(fixed_content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content=fixed_content,
            citations=citations,
            word_count=len(fixed_content.split()),
        )

    @staticmethod
    def _format_sources(sources: list[Source]) -> str:
        """Format raw sources for use in prompts."""
        lines = []
        for i, source in enumerate(sources[:8], 1):
            lines.append(f"[{i}] {source.title}")
        return "\n".join(lines) if lines else "Источники не предоставлены."
