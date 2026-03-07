"""Complete research stage — orchestrates query expansion, search, scraping, ranking."""

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.research.query_expander import QueryExpander
from backend.app.pipeline.research.ranker import SourceRanker
from backend.app.pipeline.research.scraper import WebScraper
from backend.app.pipeline.research.searcher import SearchProvider
from shared.schemas.pipeline import PipelineConfig, ResearchResult

logger = structlog.get_logger()


class ResearchStage:
    """Orchestrates the full deep research pipeline stage.

    Flow: Topic → Query Expansion → Parallel Search → Scrape → Rank → ResearchResult
    """

    def __init__(
        self,
        llm: LLMProvider,
        search_provider: SearchProvider,
        *,
        scraper: WebScraper | None = None,
        ranker: SourceRanker | None = None,
    ) -> None:
        self._query_expander = QueryExpander(llm)
        self._search_provider = search_provider
        self._scraper = scraper or WebScraper()
        self._ranker = ranker or SourceRanker()
        self._llm = llm

    async def run(
        self,
        topic: str,
        discipline: str = "",
        config: PipelineConfig | None = None,
    ) -> ResearchResult:
        """Execute the full research stage.

        Args:
            topic: Coursework topic string.
            discipline: Academic discipline for context.
            config: Pipeline configuration.

        Returns:
            ResearchResult with sources and metadata.
        """
        config = config or PipelineConfig()

        logger.info("research_stage_start", topic=topic[:80])

        # Step 1: Expand topic into multiple search queries
        queries = await self._query_expander.expand(
            topic=topic,
            discipline=discipline,
            count=6,
            model=config.light_model,
        )

        # Step 2: Search across all queries
        all_sources = []
        for query in queries:
            results = await self._search_provider.search(
                query=query,
                max_results=config.max_search_results // len(queries) + 1,
            )
            all_sources.extend(results)

        logger.info("search_complete", total_raw_sources=len(all_sources))

        # Step 3: Scrape full text for sources that need it
        all_sources = await self._scraper.scrape_sources(all_sources)

        # Step 4: Rank and deduplicate
        ranked_sources = self._ranker.rank_and_filter(
            all_sources,
            max_sources=config.max_sources,
        )

        result = ResearchResult(
            original_topic=topic,
            expanded_queries=queries,
            sources=ranked_sources,
        )

        logger.info(
            "research_stage_complete",
            topic=topic[:80],
            queries=len(queries),
            sources=len(ranked_sources),
        )

        return result
