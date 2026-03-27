"""Outline generation for scientific article structure."""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from backend.app.pipeline.writer.outline_parser import parse_outline_text
from shared.schemas.pipeline import Outline, OutlineChapter, ResearchResult

logger = structlog.get_logger()

ARTICLE_OUTLINE_PROMPT = """Ты — опытный научный автор. Составь структуру научной статьи.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}
ЦЕЛЕВОЕ КОЛИЧЕСТВО СТРАНИЦ: {page_count}

ИССЛЕДОВАННЫЕ ИСТОЧНИКИ (краткое описание):
{sources_summary}

ТРЕБОВАНИЯ К СТРУКТУРЕ НАУЧНОЙ СТАТЬИ:
1. Аннотация (краткое описание цели, методов и результатов)
2. Ключевые слова (5-7 ключевых слов)
3. Введение (актуальность, проблема, цель исследования)
4. От 2 до 4 разделов основной части (БЕЗ подразделов — статья имеет плоскую структуру)
5. Заключение (выводы, практическая значимость)

ТРЕБОВАНИЯ К ПЛАНУ:
- Названия разделов должны быть конкретными и отражать содержание
- Каждый раздел логически следует за предыдущим
- Первый раздел — теоретическая база / обзор литературы
- Последний раздел — результаты / обсуждение
- Статья должна быть сфокусирована на одной конкретной проблеме
{custom_outline_block}
Ответь строго в JSON формате:
{{
  "title": "Название статьи",
  "abstract_points": ["ключевой пункт аннотации 1", "пункт 2", ...],
  "keywords": ["ключевое слово 1", "слово 2", ...],
  "introduction_points": ["пункт введения 1", "пункт 2", ...],
  "sections": [
    {{
      "number": 1,
      "title": "Название раздела",
      "description": "Краткое описание содержания раздела",
      "estimated_pages": 3
    }}
  ],
  "conclusion_points": ["вывод 1", "вывод 2", ...]
}}"""


class ArticleOutliner:
    """Generates a structured outline for a scientific article."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def generate(
        self,
        topic: str,
        discipline: str,
        page_count: int,
        research: ResearchResult,
        model: str | None = None,
        custom_outline: str = "",
    ) -> Outline:
        """Generate a scientific article outline based on research results."""
        # Try direct parsing first for custom outlines
        if custom_outline:
            parsed = parse_outline_text(custom_outline, topic=topic, page_count=page_count)
            if parsed and parsed.chapters:
                # Articles have flat structure — clear subsections
                for ch in parsed.chapters:
                    ch.subsections = []
                logger.info("article_outline_parsed_directly", chapters=len(parsed.chapters))
                return parsed
            logger.info("article_outline_parser_fallback_to_llm")

        sources_summary = self._summarize_sources(research)

        if custom_outline:
            # Escape braces to prevent format-string injection from user input
            safe_outline = custom_outline.replace("{", "{{").replace("}", "}}")
            custom_outline_block = (
                "\nПОЛЬЗОВАТЕЛЬСКИЙ ПЛАН (ОБЯЗАТЕЛЬНО СЛЕДУЙ ЭТОЙ СТРУКТУРЕ):\n"
                "Пользователь предоставил свою структуру статьи. Следуй ей максимально точно.\n\n"
                f"{safe_outline}\n"
            )
        else:
            custom_outline_block = ""

        prompt = ARTICLE_OUTLINE_PROMPT.format(
            topic=topic,
            discipline=discipline or "не указана",
            page_count=page_count,
            sources_summary=sources_summary,
            custom_outline_block=custom_outline_block,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.5,
            max_tokens=2048,
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)

            # Map article sections to OutlineChapter (reuse existing schema)
            chapters = []
            for sec in data.get("sections", []):
                chapters.append(
                    OutlineChapter(
                        number=sec["number"],
                        title=sec["title"],
                        subsections=[],  # Articles have flat structure
                        description=sec.get("description", ""),
                        estimated_pages=sec.get("estimated_pages", 2),
                    )
                )

            # Store keywords and abstract in introduction_points
            keywords = data.get("keywords", [])
            abstract_points = data.get("abstract_points", [])
            intro_points = data.get("introduction_points", [])

            outline = Outline(
                title=data.get("title", topic),
                introduction_points=intro_points,
                chapters=chapters,
                conclusion_points=data.get("conclusion_points", []),
                # Store article-specific data in metadata fields
                keywords=keywords,
                abstract_points=abstract_points,
            )

            logger.info(
                "article_outline_generated",
                title=outline.title[:80],
                sections=len(outline.chapters),
                keywords=len(keywords),
            )
            return outline

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("article_outline_generation_failed", error=str(e))
            return Outline(
                title=topic,
                introduction_points=["Актуальность темы", "Цель исследования"],
                chapters=[
                    OutlineChapter(
                        number=1,
                        title="Теоретические основы",
                        subsections=[],
                        estimated_pages=page_count // 3,
                    ),
                    OutlineChapter(
                        number=2,
                        title="Результаты и обсуждение",
                        subsections=[],
                        estimated_pages=page_count // 3,
                    ),
                ],
                conclusion_points=["Основные выводы исследования"],
                keywords=["исследование", "анализ"],
                abstract_points=["Цель работы", "Основные результаты"],
            )

    @staticmethod
    def _summarize_sources(research: ResearchResult) -> str:
        lines = []
        for i, source in enumerate(research.sources[:10], 1):
            snippet = source.snippet or source.full_text[:200]
            lines.append(f"{i}. [{source.title}] — {snippet}")
        return "\n".join(lines) if lines else "Источники не найдены"
