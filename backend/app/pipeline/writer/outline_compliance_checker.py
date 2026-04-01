"""Outline compliance checker — verifies written sections match the user's plan.

After all sections are written, this checker:
1. Verifies each outline chapter/subsection has a corresponding section
2. Uses LLM to check if section content actually covers the topic from the plan
3. Returns issues with suggestions for rewriting
"""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    ComplianceIssue,
    ComplianceResult,
    Outline,
    SectionContent,
)

logger = structlog.get_logger()

_COMPLIANCE_CHECK_PROMPT = """Ты — строгий рецензент курсовых работ. Проверь, соответствует ли текст раздела заявленной теме из плана.

ЗАЯВЛЕННАЯ ТЕМА РАЗДЕЛА (из плана):
Глава {chapter_number}: {chapter_title}
Раздел: {section_title}

ТЕКСТ РАЗДЕЛА (первые 1500 символов):
{section_text}

Оцени:
1. Соответствует ли содержание текста заявленной теме раздела?
2. Раскрыта ли тема достаточно полно?
3. Есть ли отклонения от темы?

Ответь строго в JSON:
{{
  "is_compliant": true/false,
  "issue_type": "off_topic" | "missing_content" | "none",
  "description": "Краткое описание проблемы (или пустая строка если всё ок)",
  "suggestion": "Что нужно исправить (или пустая строка если всё ок)",
  "missing_topics": ["тема 1 которую нужно раскрыть", ...]
}}"""


class OutlineComplianceChecker:
    """Checks that written sections comply with the user's outline plan."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def check(
        self,
        outline: Outline,
        sections: list[SectionContent],
        model: str | None = None,
    ) -> ComplianceResult:
        """Check all body sections against the outline plan.

        Args:
            outline: The outline (from user's plan).
            sections: Written sections.
            model: LLM model to use for checking.

        Returns:
            ComplianceResult with issues found.
        """
        issues: list[ComplianceIssue] = []
        sections_checked = 0

        # Build a map of sections by (chapter_number, section_title)
        section_map: dict[tuple[int, str], SectionContent] = {}
        for sec in sections:
            key = (sec.chapter_number, sec.section_title)
            section_map[key] = sec

        for chapter in outline.chapters:
            section_titles = chapter.subsections if chapter.subsections else [chapter.title]

            for section_title in section_titles:
                # Find the matching written section
                matching_section = self._find_section(
                    section_map, chapter.number, section_title
                )

                if matching_section is None:
                    issues.append(ComplianceIssue(
                        section_title=section_title,
                        chapter_number=chapter.number,
                        issue_type="missing_content",
                        description=f"Раздел '{section_title}' из плана не найден в тексте",
                        suggestion=f"Написать раздел '{section_title}' по плану",
                    ))
                    sections_checked += 1
                    continue

                # Check content compliance via LLM
                issue = await self._check_section_compliance(
                    chapter_number=chapter.number,
                    chapter_title=chapter.title,
                    section_title=section_title,
                    section=matching_section,
                    model=model,
                )
                sections_checked += 1

                if issue:
                    issues.append(issue)

        compliant_count = sections_checked - len(issues)

        logger.info(
            "compliance_check_complete",
            checked=sections_checked,
            compliant=compliant_count,
            issues=len(issues),
        )

        return ComplianceResult(
            issues=issues,
            sections_checked=sections_checked,
            sections_compliant=compliant_count,
        )

    async def _check_section_compliance(
        self,
        chapter_number: int,
        chapter_title: str,
        section_title: str,
        section: SectionContent,
        model: str | None = None,
    ) -> ComplianceIssue | None:
        """Check a single section against its outline entry using LLM."""
        # Check more than the first paragraph to reduce false negatives.
        section_text = section.content[:2500]

        prompt = _COMPLIANCE_CHECK_PROMPT.format(
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            section_title=section_title,
            section_text=section_text,
        )

        try:
            response = await self._llm.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                model=model,
                temperature=0.2,
                max_tokens=512,
            )

            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()

            data = json.loads(content)

            if data.get("is_compliant", True):
                return None

            return ComplianceIssue(
                section_title=section_title,
                chapter_number=chapter_number,
                issue_type=data.get("issue_type", "off_topic"),
                description=data.get("description", "Содержание не соответствует плану"),
                suggestion=data.get("suggestion", ""),
                missing_topics=data.get("missing_topics", []),
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(
                "compliance_check_parse_error",
                section=section_title[:50],
                error=str(e),
            )
            return ComplianceIssue(
                section_title=section_title,
                chapter_number=chapter_number,
                issue_type="validation_error",
                description="РќРµ СѓРґР°Р»РѕСЃСЊ РЅР°РґС‘Р¶РЅРѕ РїСЂРѕРІРµСЂРёС‚СЊ СЃРѕРѕС‚РІРµС‚СЃС‚РІРёРµ СЂР°Р·РґРµР»Р° РїР»Р°РЅСѓ.",
                suggestion="РџРµСЂРµРїРёСЃР°С‚СЊ Рё РїРѕРІС‚РѕСЂРЅРѕ РїСЂРѕРІРµСЂРёС‚СЊ СЂР°Р·РґРµР» РїРѕ СѓС‚РѕС‡РЅС‘РЅРЅРѕРјСѓ РїР»Р°РЅСѓ.",
            )

    @staticmethod
    def _find_section(
        section_map: dict[tuple[int, str], SectionContent],
        chapter_number: int,
        section_title: str,
    ) -> SectionContent | None:
        """Find a section by chapter number and title, with fuzzy matching."""
        # Exact match
        key = (chapter_number, section_title)
        if key in section_map:
            return section_map[key]

        # Fuzzy: try matching by chapter number and partial title
        section_title_lower = section_title.lower().strip()
        for (ch_num, title), sec in section_map.items():
            if ch_num == chapter_number:
                title_lower = title.lower().strip()
                # Check if one contains the other (handles numbering differences)
                if section_title_lower in title_lower or title_lower in section_title_lower:
                    return sec
                # Strip numbering prefix (e.g., "1.1 " or "1.1. ") and compare
                import re
                clean_plan = re.sub(r"^\d+\.\d+\.?\s*", "", section_title_lower)
                clean_written = re.sub(r"^\d+\.\d+\.?\s*", "", title_lower)
                if clean_plan and clean_written and (
                    clean_plan in clean_written or clean_written in clean_plan
                ):
                    return sec

        return None
