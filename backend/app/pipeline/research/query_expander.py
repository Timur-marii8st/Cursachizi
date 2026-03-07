"""Query expansion — generates diverse search queries from a topic."""

import json

import structlog

from backend.app.llm.provider import LLMMessage, LLMProvider

logger = structlog.get_logger()

QUERY_EXPANSION_PROMPT = """Ты — исследовательский помощник. Твоя задача — сгенерировать поисковые запросы для глубокого исследования темы курсовой работы.

Тема: {topic}
Дисциплина: {discipline}

Сгенерируй {count} различных поисковых запросов на русском языке, которые помогут найти:
1. Теоретические основы темы
2. Современные исследования и публикации
3. Практические примеры и кейсы
4. Статистические данные и факты
5. Различные точки зрения и дискуссии

Запросы должны быть разнообразными — от общих до узкоспециализированных.

Ответь в формате JSON:
{{"queries": ["запрос 1", "запрос 2", ...]}}"""


class QueryExpander:
    """Expands a single topic into multiple diverse search queries."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def expand(
        self,
        topic: str,
        discipline: str = "",
        count: int = 6,
        model: str | None = None,
    ) -> list[str]:
        """Generate expanded search queries for a topic.

        Args:
            topic: The coursework topic.
            discipline: Academic discipline for context.
            count: Number of queries to generate.
            model: Optional model override.

        Returns:
            List of search query strings.
        """
        prompt = QUERY_EXPANSION_PROMPT.format(
            topic=topic,
            discipline=discipline or "не указана",
            count=count,
        )

        response = await self._llm.generate(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.8,
            max_tokens=1024,
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]).strip()
            data = json.loads(content)
            queries = data.get("queries", [])
            logger.info("query_expansion_complete", topic=topic, query_count=len(queries))
            return queries[:count]
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("query_expansion_failed", error=str(e), raw=response.content[:200])
            # Fallback: use the topic itself as the only query
            return [topic]
