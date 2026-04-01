"""Complete writer stage for scientific articles."""

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.writer.article_outliner import ArticleOutliner
from backend.app.pipeline.writer.article_section_writer import ArticleSectionWriter
from shared.schemas.pipeline import (
    BibliographyRegistry,
    Outline,
    OutlineChapter,
    PipelineConfig,
    ResearchResult,
    SectionBrief,
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
        custom_outline: str = "",
    ) -> Outline:
        config = config or PipelineConfig()
        return await self._outliner.generate(
            topic=topic,
            discipline=discipline,
            page_count=page_count,
            research=research,
            model=config.writer_model,
            custom_outline=custom_outline,
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
        bibliography: BibliographyRegistry | None = None,
    ) -> list[SectionContent]:
        """Write all sections of the article."""
        config = config or PipelineConfig()
        model = config.writer_model
        all_sections: list[SectionContent] = []

        if bibliography is None:
            bibliography = BibliographyRegistry.from_sources(research.sources)
        logger.info("article_bibliography_registry_built", entries=len(bibliography.entries))

        total_sections = 3 + len(outline.chapters)
        sections_done = 0

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

        logger.info("writing_article_introduction")
        intro_words = max(300, (page_count * 250) // 6)
        intro = await self._section_writer.write_introduction(
            topic=topic,
            discipline=discipline,
            outline=outline,
            target_words=intro_words,
            model=model,
            sources=research.sources,
            bibliography=bibliography,
        )
        all_sections.append(intro)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        body_pages = page_count - 2
        words_per_section = (body_pages * 250) // max(len(outline.chapters), 1)
        section_briefs = self._build_section_briefs(outline)

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
                bibliography=bibliography,
                section_brief=section_briefs[chapter.number],
            )
            all_sections.append(section)
            sections_done += 1
            if progress_callback:
                await progress_callback(sections_done, total_sections)

        logger.info("writing_article_conclusion")
        conclusion_words = max(250, (page_count * 250) // 8)
        conclusion = await self._section_writer.write_conclusion(
            topic=topic,
            outline=outline,
            sections=all_sections,
            target_words=conclusion_words,
            model=model,
            sources=research.sources,
            bibliography=bibliography,
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

    async def rewrite_section(
        self,
        *,
        paper_title: str,
        chapter: OutlineChapter,
        section_title: str,
        sources: list,
        previous_sections: list[SectionContent],
        target_words: int,
        additional_instructions: str = "",
        model: str | None = None,
        bibliography: BibliographyRegistry | None = None,
    ) -> SectionContent:
        """Public rewrite entry point used by orchestrator/compliance flows."""
        section_brief = self._build_section_briefs(
            Outline(title=paper_title, chapters=[chapter])
        ).get(chapter.number)
        return await self._section_writer.write_section(
            paper_title=paper_title,
            chapter=chapter,
            sources=sources,
            previous_sections=previous_sections,
            target_words=target_words,
            additional_instructions=additional_instructions,
            model=model,
            bibliography=bibliography,
            section_brief=section_brief,
        )

    @staticmethod
    def _build_section_briefs(outline: Outline) -> dict[int, SectionBrief]:
        """Build a structured writing contract for each article section."""
        briefs: dict[int, SectionBrief] = {}
        total = len(outline.chapters)
        for index, chapter in enumerate(outline.chapters, start=1):
            section_summary = chapter.description.strip() or (
                f"Focus on the section topic '{chapter.title}' and keep the argument tight."
            )
            excluded_topics = [other.title for other in outline.chapters if other.number != chapter.number]
            briefs[chapter.number] = SectionBrief(
                chapter_number=chapter.number,
                chapter_title=chapter.title,
                section_title=chapter.title,
                chapter_description=chapter.description.strip(),
                section_summary=section_summary,
                expected_topics=[chapter.title],
                excluded_topics=excluded_topics,
                section_position=index,
                total_sections_in_chapter=total,
            )
        return briefs
