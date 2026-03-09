"""Section evaluator — checks quality of each written section
and triggers rewrites when criteria are not met."""

import re

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    BibliographyRegistry,
    OutlineChapter,
    SectionContent,
    SectionEvaluation,
    Source,
)

logger = structlog.get_logger()

REWRITE_PROMPT = """Ты — опытный автор научных работ на русском языке. Перепиши раздел курсовой работы, устранив указанные недостатки.

РАЗДЕЛ: {section_title} (Глава {chapter_number})

ТЕКУЩИЙ ТЕКСТ:
{current_text}

ЗАМЕЧАНИЯ:
{feedback}

РЕЕСТР ИСТОЧНИКОВ (используй ТОЛЬКО эти источники, ссылайся по их номерам [N]):
{sources_text}

ТРЕБОВАНИЯ:
1. Устрани ВСЕ указанные недостатки
2. Сохрани академический стиль (третье лицо, безличные конструкции)
3. Ссылки на источники ТОЛЬКО в формате [N], где N — номер из РЕЕСТРА выше
4. НЕ выдумывай свои источники — используй ТОЛЬКО номера из реестра
5. Объём: примерно {target_words} слов
6. Не используй маркированные списки — только связный текст
7. Каждый абзац начинается с красной строки
8. НЕ добавляй список литературы в конце раздела

Напиши ТОЛЬКО исправленный текст раздела, без списка литературы."""


class SectionEvaluator:
    """Evaluates section quality and triggers rewrites if needed."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def evaluate(
        self,
        section: SectionContent,
        target_words: int,
        min_citations: int = 2,
        previous_sections: list[SectionContent] | None = None,
    ) -> SectionEvaluation:
        """Evaluate a section against quality criteria.

        Rules-based evaluation (no LLM call needed):
        - Word count within 60-150% of target
        - At least min_citations citation references
        - No significant content duplication with previous sections
        """
        issues = []

        # Word count check
        word_count_ok = section.word_count >= int(target_words * 0.6)
        if not word_count_ok:
            issues.append(
                f"Слишком мало слов: {section.word_count} из целевых {target_words}. "
                f"Необходимо расширить раздел."
            )

        # Citation check (skip for intro/conclusion)
        is_body_section = 0 < section.chapter_number < 99
        citations = list(set(re.findall(r"\[(\d+)\]", section.content)))
        citations_ok = len(citations) >= min_citations if is_body_section else True
        if not citations_ok:
            issues.append(
                f"Недостаточно ссылок на источники: {len(citations)} из минимальных {min_citations}. "
                f"Добавьте ссылки в формате [N]."
            )

        # Duplication check
        no_duplication = True
        if previous_sections:
            for prev in previous_sections:
                overlap = self._calculate_overlap(section.content, prev.content)
                if overlap > 0.3:
                    no_duplication = False
                    issues.append(
                        f"Высокое пересечение (~{int(overlap * 100)}%) с разделом "
                        f"«{prev.section_title}». Перефразируйте повторяющиеся фрагменты."
                    )
                    break

        passed = word_count_ok and citations_ok and no_duplication
        feedback = "\n".join(f"- {i}" for i in issues) if issues else ""

        return SectionEvaluation(
            section_title=section.section_title,
            passed=passed,
            word_count_ok=word_count_ok,
            citations_ok=citations_ok,
            no_duplication=no_duplication,
            feedback=feedback,
        )

    async def rewrite(
        self,
        section: SectionContent,
        evaluation: SectionEvaluation,
        chapter: OutlineChapter,
        sources: list[Source],
        target_words: int,
        model: str | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Rewrite a section based on evaluation feedback."""
        if bibliography:
            sources_text = bibliography.format_with_content(sources)
        else:
            sources_text = self._format_sources(sources)

        prompt = REWRITE_PROMPT.format(
            section_title=section.section_title,
            chapter_number=chapter.number,
            current_text=section.content,
            feedback=evaluation.feedback,
            sources_text=sources_text,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.7,
            max_tokens=4000,
        )

        content = response.content.strip()
        citations = list(set(re.findall(r"\[(\d+)\]", content)))

        logger.info(
            "section_rewritten",
            section=section.section_title[:50],
            old_words=section.word_count,
            new_words=len(content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=section.chapter_number,
            section_title=section.section_title,
            content=content,
            citations=citations,
            word_count=len(content.split()),
        )

    @staticmethod
    def _calculate_overlap(text_a: str, text_b: str) -> float:
        """Calculate n-gram overlap ratio between two texts.

        Uses 4-word shingles for overlap detection.
        """
        def shingles(text: str, n: int = 4) -> set[str]:
            words = text.lower().split()
            if not words:
                return set()
            if len(words) < n:
                return {" ".join(words)}
            return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}

        shingles_a = shingles(text_a)
        shingles_b = shingles(text_b)

        if not shingles_a or not shingles_b:
            return 0.0

        intersection = shingles_a & shingles_b
        smaller = min(len(shingles_a), len(shingles_b))
        return len(intersection) / smaller if smaller > 0 else 0.0

    @staticmethod
    def _format_sources(sources: list[Source]) -> str:
        lines = []
        for i, source in enumerate(sources[:8], 1):
            text = source.full_text[:1000] if source.full_text else source.snippet
            lines.append(f"[{i}] {source.title}\n{text}")
        return "\n\n".join(lines) if lines else "Источники не предоставлены."
