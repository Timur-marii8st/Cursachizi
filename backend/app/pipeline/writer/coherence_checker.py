"""Cross-section coherence checker — ensures terminology consistency,
logical flow, and cross-references between sections."""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    CoherenceIssue,
    CoherenceResult,
    SectionContent,
)

logger = structlog.get_logger()

COHERENCE_CHECK_PROMPT = """Ты — эксперт по рецензированию научных работ на русском языке.

Проанализируй следующие разделы курсовой работы на предмет СВЯЗНОСТИ и СОГЛАСОВАННОСТИ.

РАЗДЕЛЫ:
{sections_text}

Проверь:
1. **Терминологическая согласованность** — одни и те же понятия называются одинаково во всех разделах
2. **Противоречия** — нет ли утверждений в одном разделе, которые противоречат другому
3. **Перекрёстные ссылки** — где уместно добавить "как было показано в Главе N...", "ранее мы отмечали..."
4. **Логические переходы** — каждый раздел логически вытекает из предыдущего

Ответь ТОЛЬКО в формате JSON:
{{
  "issues": [
    {{
      "issue_type": "terminology|contradiction|missing_reference|logic_gap",
      "description": "Описание проблемы",
      "section_a": "Название раздела A",
      "section_b": "Название раздела B (если применимо)",
      "suggestion": "Как исправить"
    }}
  ]
}}

Если проблем нет, верни {{"issues": []}}."""

COHERENCE_FIX_PROMPT = """Ты — редактор научных работ. Исправь следующий раздел курсовой с учётом замечаний.

РАЗДЕЛ: {section_title}
ТЕКУЩИЙ ТЕКСТ:
{current_text}

ЗАМЕЧАНИЯ К ИСПРАВЛЕНИЮ:
{issues_text}

ТРЕБОВАНИЯ:
- Исправь ТОЛЬКО указанные проблемы
- Сохрани академический стиль
- Не меняй структуру и объём текста существенно
- Не удаляй существующие ссылки на источники [N]

Напиши ТОЛЬКО исправленный текст раздела."""


class CoherenceChecker:
    """Checks and fixes coherence issues across all written sections."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def check(
        self,
        sections: list[SectionContent],
        model: str | None = None,
    ) -> CoherenceResult:
        """Analyze all sections for coherence issues."""
        if len(sections) < 2:
            return CoherenceResult()

        sections_text = self._format_sections_for_check(sections)

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=COHERENCE_CHECK_PROMPT.format(
                sections_text=sections_text,
            ))],
            model=model,
            temperature=0.3,
            max_tokens=4000,
        )

        issues = self._parse_issues(response.content)
        logger.info("coherence_check_done", issues_found=len(issues))

        return CoherenceResult(
            issues_found=len(issues),
            issues=issues,
        )

    async def fix(
        self,
        sections: list[SectionContent],
        coherence_result: CoherenceResult,
        model: str | None = None,
    ) -> tuple[list[SectionContent], CoherenceResult]:
        """Apply fixes for coherence issues to affected sections.

        Returns updated sections list and updated CoherenceResult with fix counts.
        """
        if not coherence_result.issues:
            return sections, coherence_result

        # Group issues by section
        section_issues: dict[str, list[CoherenceIssue]] = {}
        for issue in coherence_result.issues:
            for section_name in [issue.section_a, issue.section_b]:
                if section_name:
                    section_issues.setdefault(section_name, []).append(issue)

        fixes_applied = 0
        sections_modified = []
        updated_sections = list(sections)

        for i, section in enumerate(updated_sections):
            matching_issues = section_issues.get(section.section_title, [])
            if not matching_issues:
                continue

            issues_text = "\n".join(
                f"- [{iss.issue_type}] {iss.description}. Рекомендация: {iss.suggestion}"
                for iss in matching_issues
            )

            response = await self._llm.generate(
                messages=[LLMMessage(role="user", content=COHERENCE_FIX_PROMPT.format(
                    section_title=section.section_title,
                    current_text=section.content,
                    issues_text=issues_text,
                ))],
                model=model,
                temperature=0.4,
                max_tokens=4000,
            )

            fixed_content = response.content.strip()
            if fixed_content and fixed_content != section.content:
                updated_sections[i] = SectionContent(
                    chapter_number=section.chapter_number,
                    section_title=section.section_title,
                    content=fixed_content,
                    citations=section.citations,
                    word_count=len(fixed_content.split()),
                )
                fixes_applied += 1
                sections_modified.append(section.section_title)

        coherence_result.fixes_applied = fixes_applied
        coherence_result.sections_modified = sections_modified

        logger.info(
            "coherence_fixes_applied",
            fixes=fixes_applied,
            sections=sections_modified,
        )

        return updated_sections, coherence_result

    def _format_sections_for_check(self, sections: list[SectionContent]) -> str:
        """Format sections for the coherence check prompt.

        Uses summaries to fit within context window limits.
        """
        parts = []
        for s in sections:
            # Use first ~500 words + last ~200 words for each section
            words = s.content.split()
            if len(words) > 700:
                excerpt = " ".join(words[:500]) + "\n[...]\n" + " ".join(words[-200:])
            else:
                excerpt = s.content
            parts.append(f"### {s.section_title}\n{excerpt}\n")
        return "\n".join(parts)

    def _parse_issues(self, response_text: str) -> list[CoherenceIssue]:
        """Parse LLM JSON response into CoherenceIssue objects."""
        try:
            # Extract JSON from response (may be wrapped in markdown code block)
            text = response_text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)
            issues_data = data.get("issues", [])

            return [
                CoherenceIssue(
                    issue_type=item.get("issue_type") or "logic_gap",
                    description=item.get("description") or "",
                    section_a=item.get("section_a") or "",
                    section_b=item.get("section_b") or "",
                    suggestion=item.get("suggestion") or "",
                )
                for item in issues_data
                if item.get("description")
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("coherence_parse_failed", error=str(e))
            return []
