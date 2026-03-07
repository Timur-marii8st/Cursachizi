"""Complete writer stage for scientific articles."""

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.writer.article_outliner import ArticleOutliner
from backend.app.pipeline.writer.article_section_writer import ArticleSectionWriter
from shared.schemas.pipeline import (
    Outline,
    PipelineConfig,
    ResearchResult,
    SectionContent,
)

logger = structlog.get_logger()


class ArticleWriterStage:
    """Orchestrates outline generation and section writing for scientific articles."""

    def __init__(self, llm: LLMProvider) -> None:
        self._outliner = ArticleOutliner(llm)
        self._section_writer = ArticleSectionWriter(llm)

    async def generate_outline(
        self,
        topic: str,
        discipline: str,
        page_count: int,
        research: ResearchResult,
        config: PipelineConfig | None = None,
    ) -> Outline:
        config = config or PipelineConfig()
        return await self._outliner.generate(
            topic=topic,
            discipline=discipline,
            page_count=page_count,
            research=research,
            model=config.writer_model,
        )

    async def write_all_sections(
        self,
        topic: str,
        discipline: str,
        page_count: int,
        outline: Outline,
        research: ResearchResult,
        additional_instructions: str = "",
        config: PipelineConfig | None = None,
        progress_callback=None,
    ) -> list[SectionContent]:
        """Write all sections of the article."""
        config = config or PipelineConfig()
        model = config.writer_model
        all_sections: list[SectionContent] = []

        # Total sections: abstract + intro + body sections + conclusion
        total_sections = 3 + len(outline.chapters)  # abstract + intro + sections + conclusion
        sections_done = 0

        # Step 1: Write abstract
        logger.info("writing_article_abstract")
        abstract = await self._section_writer.write_abstract(
            topic=topic,
            outline=outline,
            model=model,
        )
        all_sections.append(abstract)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        # Step 2: Write introduction
        logger.info("writing_article_introduction")
        # Intro ~15% of body
        intro_words = max(300, (page_count * 250) // 6)
        intro = await self._section_writer.write_introduction(
            topic=topic,
            discipline=discipline,
            outline=outline,
            target_words=intro_words,
            model=model,
        )
        all_sections.append(intro)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        # Step 3: Write each section
        # Articles have flat structure (no subsections)
        body_pages = page_count - 2  # Minus intro/conclusion/abstract
        words_per_section = (body_pages * 250) // max(len(outline.chapters), 1)

        for chapter in outline.chapters:
            logger.info("writing_article_section", section=chapter.title[:50])
            section = await self._section_writer.write_section(
                paper_title=outline.title,
                chapter=chapter,
                sources=research.sources,
                previous_sections=all_sections,
                target_words=words_per_section,
                additional_instructions=additional_instructions,
                model=model,
            )
            all_sections.append(section)
            sections_done += 1
            if progress_callback:
                await progress_callback(sections_done, total_sections)

        # Step 4: Write conclusion
        logger.info("writing_article_conclusion")
        conclusion_words = max(250, (page_count * 250) // 8)
        conclusion = await self._section_writer.write_conclusion(
            topic=topic,
            outline=outline,
            sections=all_sections,
            target_words=conclusion_words,
            model=model,
        )
        all_sections.append(conclusion)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        total_words = sum(s.word_count for s in all_sections)
        logger.info(
            "article_writing_complete",
            total_sections=len(all_sections),
            total_words=total_words,
        )

        return all_sections
