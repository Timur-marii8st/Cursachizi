"""Section writing for scientific articles."""

import re

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from shared.schemas.pipeline import (
    BibliographyRegistry,
    Outline,
    OutlineChapter,
    SectionBrief,
    SectionContent,
    Source,
)

logger = structlog.get_logger()

ARTICLE_SECTION_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши раздел научной статьи.

НАЗВАНИЕ СТАТЬИ: {paper_title}
РАЗДЕЛ {section_number}: {section_title}

SECTION CONTRACT:
{section_contract}

КОНТРАКТ РАЗДЕЛА:
{section_contract}

КОНТЕКСТ ПРЕДЫДУЩИХ РАЗДЕЛОВ:
{previous_context}

РЕЕСТР ИСТОЧНИКОВ (используй ТОЛЬКО эти источники):
{sources_text}

ТРЕБОВАНИЯ:
1. Строгий научный стиль (третье лицо, безличные конструкции, научная терминология)
2. Логичная структура: постановка вопроса → анализ → выводы
3. Обязательные ссылки на источники в формате [N] (где N — номер из реестра выше) по тексту
4. Минимум 3-4 ссылки на источники в каждом разделе
5. Объём: примерно {target_words} слов
6. Не используй маркированные списки — только связный текст с абзацами
7. Каждый абзац начинается с красной строки
8. Текст должен быть аналитическим, а не описательным
9. НЕ используй markdown-разметку (**, ##, `, * и т.д.) — пиши чистый текст
10. НЕ используй HTML-сущности (&nbsp; и т.д.)
11. НЕ выдумывай свои источники — используй ТОЛЬКО номера [N] из реестра выше
12. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять список литературы, библиографию, перечень источников или блок «Список использованных источников» в конце раздела — он будет сгенерирован автоматически
13. Ссылайся на источники СТРОГО по их номерам [N] из РЕЕСТРА ИСТОЧНИКОВ — НЕ придумывай свои номера

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ:
{additional_instructions}

Напиши ТОЛЬКО текст раздела, без заголовка и без списка литературы. Любой список источников в конце — это ОШИБКА."""

ARTICLE_INTRODUCTION_PROMPT = """Ты — опытный автор научных статей на русском языке. Напиши введение к научной статье.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}

СТРУКТУРА СТАТЬИ:
{outline_summary}

РЕЕСТР ИСТОЧНИКОВ (используй для обзора литературы, ссылайся по номерам [N]):
{sources_text}

ТРЕБОВАНИЯ К ВВЕДЕНИЮ НАУЧНОЙ СТАТЬИ:
1. Актуальность проблемы (1-2 абзаца, с опорой на современные исследования)
2. Степень изученности проблемы (краткий обзор ключевых работ с ссылками [N] из реестра)
3. Формулировка проблемы / исследовательского вопроса (чётко и конкретно)
4. Цель исследования (1 предложение)
5. Методы исследования (кратко)
6. Научная новизна (чем данная работа отличается от существующих)
7. Ссылки на источники ТОЛЬКО в формате [N], где N — номер из РЕЕСТРА ИСТОЧНИКОВ выше
8. НЕ выдумывай свои источники — используй ТОЛЬКО номера из реестра
9. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять список литературы или библиографию в конце — он будет сгенерирован автоматически
10. Ссылайся на источники СТРОГО по их номерам [N] из РЕЕСТРА ИСТОЧНИКОВ — НЕ придумывай свои номера

Объём: примерно {target_words} слов. Строгий научный стиль.
НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст.

Напиши ТОЛЬКО текст введения, без списка литературы. Любой список источников в конце — это ОШИБКА."""

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

РЕЕСТР ИСТОЧНИКОВ (при необходимости ссылайся по номерам [N]):
{sources_text}

ТРЕБОВАНИЯ К ЗАКЛЮЧЕНИЮ НАУЧНОЙ СТАТЬИ:
1. Основные результаты исследования (по каждому разделу)
2. Ответ на исследовательский вопрос / достижение цели
3. Практическая и теоретическая значимость результатов
4. Ограничения исследования
5. Направления дальнейших исследований
6. При упоминании конкретных данных используй ссылки [N] из реестра источников
7. НЕ выдумывай свои источники — используй ТОЛЬКО номера из реестра
8. Объём: примерно {target_words} слов
9. НЕ используй markdown-разметку (**, ##, ` и т.д.) — пиши чистый текст
10. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО добавлять список литературы или библиографию в конце — он будет сгенерирован автоматически
11. Ссылайся на источники СТРОГО по их номерам [N] из РЕЕСТРА ИСТОЧНИКОВ — НЕ придумывай свои номера

Напиши ТОЛЬКО текст заключения, без списка литературы. Любой список источников в конце — это ОШИБКА."""


def _safe(value: str | None) -> str:
    """Escape curly braces in user-provided strings to prevent format injection."""
    if not value:
        return ""
    return str(value).replace("{", "{{").replace("}", "}}")


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
        sources: list[Source] | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Write the article introduction."""
        outline_summary = self._format_outline(outline)

        # Build sources text for the introduction prompt
        if bibliography and bibliography.entries:
            sources_text = bibliography.format_for_prompt()
        elif sources:
            sources_text = self._format_sources(sources)
        else:
            sources_text = "Источники не предоставлены. НЕ используй ссылки [N] в тексте."

        prompt = ARTICLE_INTRODUCTION_PROMPT.format(
            topic=topic,
            discipline=discipline or "не указана",
            outline_summary=outline_summary,
            sources_text=sources_text,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.5,
            max_tokens=2000,
        )

        content = response.content.strip()
        citations = list(set(re.findall(r"\[(\d+)\]", content)))
        logger.info(
            "article_introduction_written",
            words=len(content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=0,
            section_title="Введение",
            content=content,
            citations=citations,
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
        bibliography: BibliographyRegistry | None = None,
        section_brief: SectionBrief | None = None,
    ) -> SectionContent:
        """Write a single article section."""
        previous_context = self._format_previous(previous_sections[-2:])
        section_brief = section_brief or self._build_fallback_brief(chapter)
        has_sources = (bibliography and bibliography.entries) or sources
        if bibliography and bibliography.entries:
            sources_text = bibliography.get_formatted_content_cached(sources)
        elif sources:
            sources_text = self._format_sources(sources)
        else:
            sources_text = "Источники не предоставлены."
            logger.warning(
                "article_section_writer_no_sources",
                section=chapter.title[:50],
                reason="Both bibliography and sources are empty",
            )

        # When no sources are available, override instructions to prevent hallucinated citations
        if not has_sources:
            no_cite_note = (
                "ВНИМАНИЕ: Источники не найдены. НЕ используй ссылки [N] в тексте. "
                "Пиши без цитирования, опираясь на общеизвестные факты."
            )
            effective_instructions = no_cite_note
        else:
            effective_instructions = additional_instructions or "Нет дополнительных инструкций."

        section_contract = self._format_section_brief(section_brief)

        prompt = ARTICLE_SECTION_PROMPT.format(
            paper_title=_safe(paper_title),
            section_number=chapter.number,
            section_title=_safe(chapter.title),
            section_contract=section_contract,
            previous_context=previous_context,
            sources_text=sources_text,
            target_words=target_words,
            additional_instructions=effective_instructions,
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
        sources: list[Source] | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Write the article conclusion."""
        conclusion_points = "\n".join(f"- {p}" for p in outline.conclusion_points)
        sections_summary = self._format_sections_summary(outline, sections)

        # Build sources text for the conclusion prompt
        if bibliography and bibliography.entries:
            sources_text = bibliography.format_for_prompt()
        elif sources:
            sources_text = self._format_sources(sources)
        else:
            sources_text = "Источники не предоставлены. НЕ используй ссылки [N] в тексте."

        prompt = ARTICLE_CONCLUSION_PROMPT.format(
            topic=topic,
            conclusion_points=conclusion_points,
            sections_summary=sections_summary,
            sources_text=sources_text,
            target_words=target_words,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.4,
            max_tokens=1500,
        )

        content = response.content.strip()
        citations = list(set(re.findall(r"\[(\d+)\]", content)))
        logger.info(
            "article_conclusion_written",
            words=len(content.split()),
            citations=len(citations),
        )

        return SectionContent(
            chapter_number=99,
            section_title="Заключение",
            content=content,
            citations=citations,
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
    def _build_fallback_brief(chapter: OutlineChapter) -> SectionBrief:
        section_summary = chapter.description.strip() or (
            f"Focus on the section topic '{chapter.title}' and keep the analysis on scope."
        )
        return SectionBrief(
            chapter_number=chapter.number,
            chapter_title=chapter.title,
            section_title=chapter.title,
            chapter_description=chapter.description.strip(),
            section_summary=section_summary,
            expected_topics=[chapter.title],
            excluded_topics=[],
            section_position=1,
            total_sections_in_chapter=1,
        )

    @staticmethod
    def _format_section_brief(section_brief: SectionBrief) -> str:
        lines = [
            f"- Section goal: {section_brief.section_summary}",
            (
                "- Expected topics: " + ", ".join(section_brief.expected_topics)
                if section_brief.expected_topics
                else "- Expected topics: not specified"
            ),
        ]
        if section_brief.excluded_topics:
            lines.append("- Avoid drifting into: " + ", ".join(section_brief.excluded_topics))
        return "\n".join(lines)

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
