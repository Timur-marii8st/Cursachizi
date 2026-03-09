"""Section-by-section academic content writing."""

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    CHAPTER_CONCLUSION,
    CHAPTER_INTRO,
    Outline,
    OutlineChapter,
    SectionContent,
    Source,
)

logger = structlog.get_logger()


def _safe(text: str) -> str:
    """Escape curly braces in user-provided text to prevent format-string injection.

    Without this, a topic like "Python {format} tricks" would cause KeyError
    when interpolated into prompt templates via str.format().
    """
    return text.replace("{", "{{").replace("}", "}}")


SECTION_PROMPT = """Ты — опытный автор научных работ на русском языке. Напиши раздел курсовой работы в академическом стиле.

НАЗВАНИЕ КУРСОВОЙ: {paper_title}
ГЛАВА {chapter_number}: {chapter_title}
ТЕКУЩИЙ РАЗДЕЛ: {section_title}

КОНТЕКСТ ПРЕДЫДУЩИХ РАЗДЕЛОВ:
{previous_context}

ИСТОЧНИКИ ДЛЯ ИСПОЛЬЗОВАНИЯ:
{sources_text}

ТРЕБОВАНИЯ:
1. Академический стиль изложения (третье лицо, безличные конструкции)
2. Логичная структура: тезис → аргументация → вывод
3. Обязательные ссылки на источники в формате [N] (где N — номер источника) по тексту
4. Минимум 2-3 ссылки на источники в каждом разделе
5. Объём: примерно {target_words} слов
6. Не используй маркированные списки — только связный текст с абзацами
7. Каждый абзац начинается с красной строки
8. В конце раздела — краткий промежуточный вывод
9. НЕ используй markdown-разметку (**, ##, `, * и т.д.) — пиши чистый текст
10. НЕ используй HTML-сущности (&nbsp; и т.д.)
11. ОБЯЗАТЕЛЬНО в конце раздела после основного текста добавь блок библиографических ссылок, использованных в этом разделе. Формат каждой ссылки:
[N] Фамилия И.О. Название работы. — Издательство, Год.
Пример:
[1] Иванов А.Б. Основы экономики. — М.: Наука, 2023.
[2] Smith J. Machine Learning Basics. — Springer, 2022.

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ:
{additional_instructions}

Напиши ТОЛЬКО текст раздела, без заголовка."""

INTRODUCTION_PROMPT = """Ты — опытный автор научных работ на русском языке. Напиши введение к курсовой работе.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}

СТРУКТУРА РАБОТЫ:
{outline_summary}

ТРЕБОВАНИЯ К ВВЕДЕНИЮ:
1. Актуальность темы (1-2 абзаца)
2. Степень разработанности проблемы (1 абзац, ссылки на авторов)
3. Цель исследования (1 предложение)
4. Задачи исследования (3-5 задач, каждая начинается с глагола)
5. Объект исследования
6. Предмет исследования
7. Методы исследования
8. Структура работы (краткое описание глав)

Объём: примерно {target_words} слов. Академический стиль.
НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст.

Напиши ТОЛЬКО текст введения."""

CONCLUSION_PROMPT = """Ты — опытный автор научных работ на русском языке. Напиши заключение к курсовой работе.

ТЕМА: {topic}

ПУНКТЫ ДЛЯ ВЫВОДОВ:
{conclusion_points}

КРАТКОЕ СОДЕРЖАНИЕ ГЛАВ:
{chapters_summary}

ТРЕБОВАНИЯ К ЗАКЛЮЧЕНИЮ:
1. Начни с общего вывода по теме
2. Сформулируй выводы по каждой задаче из введения
3. Укажи практическую значимость результатов
4. Обозначь направления дальнейших исследований
5. Объём: примерно {target_words} слов
6. НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст

Напиши ТОЛЬКО текст заключения."""


class SectionWriter:
    """Writes individual sections of the coursework."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def write_introduction(
        self,
        topic: str,
        discipline: str,
        outline: Outline,
        target_words: int = 800,
        model: str | None = None,
    ) -> SectionContent:
        """Write the introduction section."""
        outline_summary = self._format_outline(outline)

        prompt = INTRODUCTION_PROMPT.format(
            topic=_safe(topic),
            discipline=_safe(discipline) or "не указана",
            outline_summary=outline_summary,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.6,
            max_tokens=3000,
        )

        content = response.content.strip()
        logger.info("introduction_written", words=len(content.split()))

        return SectionContent(
            chapter_number=CHAPTER_INTRO,
            section_title="Введение",
            content=content,
            word_count=len(content.split()),
        )

    async def write_section(
        self,
        paper_title: str,
        chapter: OutlineChapter,
        section_title: str,
        sources: list[Source],
        previous_sections: list[SectionContent],
        target_words: int = 1000,
        additional_instructions: str = "",
        model: str | None = None,
    ) -> SectionContent:
        """Write a single chapter section."""
        # Build context from previous sections (last 2 for continuity)
        previous_context = self._format_previous(previous_sections[-2:])
        sources_text = self._format_sources(sources)

        prompt = SECTION_PROMPT.format(
            paper_title=_safe(paper_title),
            chapter_number=chapter.number,
            chapter_title=_safe(chapter.title),
            section_title=_safe(section_title),
            previous_context=previous_context,
            sources_text=sources_text,
            target_words=target_words,
            additional_instructions=_safe(additional_instructions) or "Нет дополнительных инструкций.",
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.7,
            max_tokens=4000,
        )

        content = response.content.strip()
        # Extract citation references [N] from text
        import re
        citations = list(set(re.findall(r"\[(\d+)\]", content)))

        logger.info(
            "section_written",
            chapter=chapter.number,
            section=section_title[:50],
            words=len(content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=chapter.number,
            section_title=section_title,
            content=content,
            citations=citations,
            word_count=len(content.split()),
        )

    async def write_conclusion(
        self,
        topic: str,
        outline: Outline,
        sections: list[SectionContent],
        target_words: int = 600,
        model: str | None = None,
    ) -> SectionContent:
        """Write the conclusion section."""
        conclusion_points = "\n".join(f"- {p}" for p in outline.conclusion_points)
        chapters_summary = self._format_chapters_summary(outline, sections)

        prompt = CONCLUSION_PROMPT.format(
            topic=_safe(topic),
            conclusion_points=conclusion_points,
            chapters_summary=chapters_summary,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.5,
            max_tokens=2000,
        )

        content = response.content.strip()
        logger.info("conclusion_written", words=len(content.split()))

        return SectionContent(
            chapter_number=CHAPTER_CONCLUSION,  # Sentinel for conclusion
            section_title="Заключение",
            content=content,
            word_count=len(content.split()),
        )

    @staticmethod
    def _format_outline(outline: Outline) -> str:
        lines = [f"Название: {outline.title}"]
        for ch in outline.chapters:
            lines.append(f"\nГлава {ch.number}: {ch.title}")
            for sub in ch.subsections:
                lines.append(f"  {sub}")
        return "\n".join(lines)

    @staticmethod
    def _format_previous(sections: list[SectionContent]) -> str:
        if not sections:
            return "Это первый раздел работы."
        parts = []
        for s in sections:
            # Include last ~300 words for context
            words = s.content.split()
            excerpt = " ".join(words[-300:]) if len(words) > 300 else s.content
            parts.append(f"[{s.section_title}]: ...{excerpt}")
        return "\n\n".join(parts)

    @staticmethod
    def _format_sources(sources: list[Source]) -> str:
        lines = []
        for i, source in enumerate(sources[:8], 1):
            text = source.full_text[:1500] if source.full_text else source.snippet
            lines.append(f"[{i}] {source.title}\n{text}\n")
        return "\n".join(lines) if lines else "Источники не предоставлены."

    @staticmethod
    def _format_chapters_summary(
        outline: Outline, sections: list[SectionContent]
    ) -> str:
        lines = []
        for ch in outline.chapters:
            ch_sections = [s for s in sections if s.chapter_number == ch.number]
            words = sum(s.word_count for s in ch_sections)
            lines.append(f"Глава {ch.number} «{ch.title}» — {words} слов, {len(ch_sections)} разделов")
        return "\n".join(lines)
