"""Section writing for scientific articles."""

import re

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    Outline,
    OutlineChapter,
    SectionContent,
    Source,
)

logger = structlog.get_logger()

ARTICLE_SECTION_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши раздел научной статьи.

НАЗВАНИЕ СТАТЬИ: {paper_title}
РАЗДЕЛ {section_number}: {section_title}

КОНТЕКСТ ПРЕДЫДУЩИХ РАЗДЕЛОВ:
{previous_context}

ИСТОЧНИКИ ДЛЯ ИСПОЛЬЗОВАНИЯ:
{sources_text}

ТРЕБОВАНИЯ:
1. Строгий научный стиль (третье лицо, безличные конструкции, научная терминология)
2. Логичная структура: постановка вопроса → анализ → выводы
3. Обязательные ссылки на источники в формате [N] (где N — номер источника) по тексту
4. Минимум 3-4 ссылки на источники в каждом разделе
5. Объём: примерно {target_words} слов
6. Не используй маркированные списки — только связный текст с абзацами
7. Каждый абзац начинается с красной строки
8. Текст должен быть аналитическим, а не описательным
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

ARTICLE_INTRODUCTION_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши введение к научной статье.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}

СТРУКТУРА СТАТЬИ:
{outline_summary}

ТРЕБОВАНИЯ К ВВЕДЕНИЮ НАУЧНОЙ СТАТЬИ:
1. Актуальность проблемы (1-2 абзаца, с опорой на современные исследования)
2. Степень изученности проблемы (краткий обзор ключевых работ)
3. Формулировка проблемы / исследовательского вопроса (чётко и конкретно)
4. Цель исследования (1 предложение)
5. Методы исследования (кратко)
6. Научная новизна (чем данная работа отличается от существующих)

Объём: примерно {target_words} слов. Строгий научный стиль.
НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст.

Напиши ТОЛЬКО текст введения."""

ARTICLE_ABSTRACT_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши аннотацию к научной статье.

ТЕМА: {topic}

КЛЮЧЕВЫЕ ПУНКТЫ:
{abstract_points}

СТРУКТУРА СТАТЬИ:
{outline_summary}

ТРЕБОВАНИЯ К АННОТАЦИИ:
1. Краткое изложение цели, методов и основных результатов
2. Объём: 150-250 слов (строго!)
3. Информативность — читатель должен понять суть статьи без чтения полного текста
4. Не используй ссылки на источники
5. Строгий научный стиль
6. НЕ используй markdown-разметку

Напиши ТОЛЬКО текст аннотации."""

ARTICLE_CONCLUSION_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши заключение к научной статье.

ТЕМА: {topic}

ПУНКТЫ ДЛЯ ВЫВОДОВ:
{conclusion_points}

КРАТКОЕ СОДЕРЖАНИЕ РАЗДЕЛОВ:
{sections_summary}

ТРЕБОВАНИЯ К ЗАКЛЮЧЕНИЮ НАУЧНОЙ СТАТЬИ:
1. Основные результаты исследования (по каждому разделу)
2. Ответ на исследовательский вопрос / достижение цели
3. Практическая и теоретическая значимость результатов
4. Ограничения исследования
5. Направления дальнейших исследований
6. Объём: примерно {target_words} слов
7. НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст

Напиши ТОЛЬКО текст заключения."""


class ArticleSectionWriter:
    """Writes sections of a scientific article."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def write_abstract(
        self,
        topic: str,
        outline: Outline,
        model: str | None = None,
    ) -> SectionContent:
        """Write the article abstract."""
        outline_summary = self._format_outline(outline)
        abstract_points = "\n".join(
            f"- {p}" for p in outline.abstract_points
        ) or "Не указаны"

        prompt = ARTICLE_ABSTRACT_PROMPT.format(
            topic=topic,
            abstract_points=abstract_points,
            outline_summary=outline_summary,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.4,
            max_tokens=1000,
        )

        content = response.content.strip()
        logger.info("article_abstract_written", words=len(content.split()))

        return SectionContent(
            chapter_number=-1,  # Sentinel for abstract
            section_title="Аннотация",
            content=content,
            word_count=len(content.split()),
        )

    async def write_introduction(
        self,
        topic: str,
        discipline: str,
        outline: Outline,
        target_words: int = 500,
        model: str | None = None,
    ) -> SectionContent:
        """Write the article introduction."""
        outline_summary = self._format_outline(outline)

        prompt = ARTICLE_INTRODUCTION_PROMPT.format(
            topic=topic,
            discipline=discipline or "не указана",
            outline_summary=outline_summary,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.5,
            max_tokens=2000,
        )

        content = response.content.strip()
        logger.info("article_introduction_written", words=len(content.split()))

        return SectionContent(
            chapter_number=0,
            section_title="Введение",
            content=content,
            word_count=len(content.split()),
        )

    async def write_section(
        self,
        paper_title: str,
        chapter: OutlineChapter,
        sources: list[Source],
        previous_sections: list[SectionContent],
        target_words: int = 600,
        additional_instructions: str = "",
        model: str | None = None,
    ) -> SectionContent:
        """Write a single article section."""
        previous_context = self._format_previous(previous_sections[-2:])
        sources_text = self._format_sources(sources)

        prompt = ARTICLE_SECTION_PROMPT.format(
            paper_title=paper_title,
            section_number=chapter.number,
            section_title=chapter.title,
            previous_context=previous_context,
            sources_text=sources_text,
            target_words=target_words,
            additional_instructions=additional_instructions or "Нет дополнительных инструкций.",
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.6,
            max_tokens=3000,
        )

        content = response.content.strip()
        citations = list(set(re.findall(r"\[(\d+)\]", content)))

        logger.info(
            "article_section_written",
            section=chapter.title[:50],
            words=len(content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=chapter.number,
            section_title=chapter.title,
            content=content,
            citations=citations,
            word_count=len(content.split()),
        )

    async def write_conclusion(
        self,
        topic: str,
        outline: Outline,
        sections: list[SectionContent],
        target_words: int = 400,
        model: str | None = None,
    ) -> SectionContent:
        """Write the article conclusion."""
        conclusion_points = "\n".join(f"- {p}" for p in outline.conclusion_points)
        sections_summary = self._format_sections_summary(outline, sections)

        prompt = ARTICLE_CONCLUSION_PROMPT.format(
            topic=topic,
            conclusion_points=conclusion_points,
            sections_summary=sections_summary,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.4,
            max_tokens=1500,
        )

        content = response.content.strip()
        logger.info("article_conclusion_written", words=len(content.split()))

        return SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content=content,
            word_count=len(content.split()),
        )

    @staticmethod
    def _format_outline(outline: Outline) -> str:
        lines = [f"Название: {outline.title}"]
        for ch in outline.chapters:
            lines.append(f"\nРаздел {ch.number}: {ch.title}")
            if ch.description:
                lines.append(f"  {ch.description}")
        return "\n".join(lines)

    @staticmethod
    def _format_previous(sections: list[SectionContent]) -> str:
        if not sections:
            return "Это первый раздел статьи."
        parts = []
        for s in sections:
            words = s.content.split()
            excerpt = " ".join(words[-200:]) if len(words) > 200 else s.content
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
    def _format_sections_summary(
        outline: Outline, sections: list[SectionContent],
    ) -> str:
        lines = []
        for ch in outline.chapters:
            ch_sections = [s for s in sections if s.chapter_number == ch.number]
            words = sum(s.word_count for s in ch_sections)
            lines.append(f"Раздел {ch.number} «{ch.title}» — {words} слов")
        return "\n".join(lines)
