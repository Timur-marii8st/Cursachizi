"""Outline generation for coursework structure."""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider
from backend.app.pipeline.writer.outline_parser import parse_outline_text
from shared.schemas.pipeline import Outline, OutlineChapter, ResearchResult

logger = structlog.get_logger()

OUTLINE_PROMPT = """Ты — опытный научный руководитель в российском университете. Составь детальный план курсовой работы.

ТЕМА: {topic}
ДИСЦИПЛИНА: {discipline}
ЦЕЛЕВОЕ КОЛИЧЕСТВО СТРАНИЦ: {page_count}

ИССЛЕДОВАННЫЕ ИСТОЧНИКИ (краткое описание):
{sources_summary}

ТРЕБОВАНИЯ К СТРУКТУРЕ:
1. Введение (актуальность, цель, задачи, объект и предмет исследования, методы)
2. От 2 до 4 глав основной части, каждая с 2-4 подразделами
3. Заключение (выводы по каждой задаче)

ТРЕБОВАНИЯ К ПЛАНУ:
- Названия глав должны быть информативными и конкретными
- Каждая глава должна логически следовать за предыдущей
- Первая глава — теоретическая (обзор литературы)
- Последняя глава — практическая/аналитическая
- Подразделы должны раскрывать содержание главы
{custom_outline_block}
Ответь строго в JSON формате:
{{
  "title": "Полное название курсовой работы",
  "introduction_points": ["пункт 1 введения", "пункт 2", ...],
  "chapters": [
    {{
      "number": 1,
      "title": "Название главы",
      "subsections": ["1.1 Подраздел", "1.2 Подраздел", ...],
      "description": "Краткое описание содержания главы",
      "estimated_pages": 8
    }}
  ],
  "conclusion_points": ["вывод 1", "вывод 2", ...]
}}"""


class Outliner:
    """Generates a structured outline for the coursework."""

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
        """Generate a coursework outline based on research results.

        Args:
            topic: Coursework topic.
            discipline: Academic discipline.
            page_count: Target page count.
            research: Research results with sources.
            model: Optional model override.
            custom_outline: User-provided outline to follow.

        Returns:
            Structured Outline object.
        """
        # If user provided a custom outline, try direct parsing first (no LLM)
        if custom_outline:
            parsed = parse_outline_text(custom_outline, topic=topic, page_count=page_count)
            if parsed and parsed.chapters:
                logger.info(
                    "outline_parsed_directly",
                    chapters=len(parsed.chapters),
                    subsections=sum(len(ch.subsections) for ch in parsed.chapters),
                )
                return parsed
            # Parser couldn't recognize structure — fall through to LLM with instructions
            logger.info("outline_parser_fallback_to_llm")

        # Summarize top sources for context
        sources_summary = self._summarize_sources(research)

        # Build custom outline instruction block
        if custom_outline:
            # Escape braces to prevent format-string injection from user input
            safe_outline = custom_outline.replace("{", "{{").replace("}", "}}")
            custom_outline_block = (
                "\nПОЛЬЗОВАТЕЛЬСКИЙ ПЛАН (ОБЯЗАТЕЛЬНО СЛЕДУЙ ЭТОЙ СТРУКТУРЕ):\n"
                "Пользователь предоставил свой план работы. Ты ДОЛЖЕН следовать этой структуре "
                "максимально точно, сохраняя названия глав и подразделов. Допускается лишь "
                "незначительная корректировка формулировок для академического стиля.\n\n"
                f"{safe_outline}\n"
            )
        else:
            custom_outline_block = ""

        prompt = OUTLINE_PROMPT.format(
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

            outline = Outline(
                title=data.get("title", topic),
                introduction_points=data.get("introduction_points", []),
                chapters=[
                    OutlineChapter(**ch) for ch in data.get("chapters", [])
                ],
                conclusion_points=data.get("conclusion_points", []),
            )

            logger.info(
                "outline_generated",
                title=outline.title[:80],
                chapters=len(outline.chapters),
            )
            return outline

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("outline_generation_failed", error=str(e))
            # Return a minimal default outline
            return Outline(
                title=topic,
                introduction_points=["Актуальность темы", "Цель и задачи исследования"],
                chapters=[
                    OutlineChapter(
                        number=1,
                        title="Теоретические основы",
                        subsections=["1.1 Основные понятия", "1.2 Обзор литературы"],
                        estimated_pages=page_count // 3,
                    ),
                    OutlineChapter(
                        number=2,
                        title="Анализ и исследование",
                        subsections=["2.1 Методология", "2.2 Результаты анализа"],
                        estimated_pages=page_count // 3,
                    ),
                    OutlineChapter(
                        number=3,
                        title="Практическая часть",
                        subsections=["3.1 Разработка рекомендаций", "3.2 Оценка эффективности"],
                        estimated_pages=page_count // 3,
                    ),
                ],
                conclusion_points=["Основные выводы исследования"],
            )

    @staticmethod
    def _summarize_sources(research: ResearchResult) -> str:
        """Create a brief summary of top sources for outline context."""
        lines = []
        for i, source in enumerate(research.sources[:10], 1):
            snippet = source.snippet or source.full_text[:200]
            lines.append(f"{i}. [{source.title}] — {snippet}")
        return "\n".join(lines) if lines else "Источники не найдены"
