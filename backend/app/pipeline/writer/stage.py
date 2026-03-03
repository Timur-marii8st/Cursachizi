"""Complete writer stage — generates all coursework content."""

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.writer.outliner import Outliner
from backend.app.pipeline.writer.section_writer import SectionWriter
from shared.schemas.pipeline import (
    Outline,
    PipelineConfig,
    ResearchResult,
    SectionContent,
)

logger = structlog.get_logger()


class WriterStage:
    """Orchestrates outline generation and section-by-section writing."""

    def __init__(self, llm: LLMProvider) -> None:
        self._outliner = Outliner(llm)
        self._section_writer = SectionWriter(llm)

    async def generate_outline(
        self,
        topic: str,
        discipline: str,
        page_count: int,
        research: ResearchResult,
        config: PipelineConfig | None = None,
    ) -> Outline:
        """Generate the coursework outline."""
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
        """Write all sections of the coursework.

        Args:
            topic: Coursework topic.
            discipline: Academic discipline.
            page_count: Target page count.
            outline: Generated outline.
            research: Research results with sources.
            additional_instructions: Extra user instructions.
            config: Pipeline configuration.
            progress_callback: Optional async callback(sections_done, sections_total).

        Returns:
            List of all written sections in order.
        """
        config = config or PipelineConfig()
        model = config.writer_model
        all_sections: list[SectionContent] = []

        # Calculate total sections for progress tracking
        total_sections = 2  # intro + conclusion
        for ch in outline.chapters:
            total_sections += max(len(ch.subsections), 1)
        sections_done = 0

        # Step 1: Write introduction
        logger.info("writing_introduction")
        intro = await self._section_writer.write_introduction(
            topic=topic,
            discipline=discipline,
            outline=outline,
            target_words=800,
            model=model,
        )
        all_sections.append(intro)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        # Step 2: Write each chapter section-by-section
        # Approximate words per section based on page count
        body_pages = page_count - 4  # Minus intro/conclusion/title/toc
        total_subsections = sum(max(len(ch.subsections), 1) for ch in outline.chapters)
        words_per_section = (body_pages * 250) // max(total_subsections, 1)  # ~250 words/page

        for chapter in outline.chapters:
            logger.info("writing_chapter", chapter=chapter.number, title=chapter.title[:50])
            sections_to_write = chapter.subsections if chapter.subsections else [chapter.title]

            for section_title in sections_to_write:
                section = await self._section_writer.write_section(
                    paper_title=outline.title,
                    chapter=chapter,
                    section_title=section_title,
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

        # Step 3: Write conclusion
        logger.info("writing_conclusion")
        conclusion = await self._section_writer.write_conclusion(
            topic=topic,
            outline=outline,
            sections=all_sections,
            target_words=600,
            model=model,
        )
        all_sections.append(conclusion)
        sections_done += 1
        if progress_callback:
            await progress_callback(sections_done, total_sections)

        total_words = sum(s.word_count for s in all_sections)
        logger.info(
            "writing_complete",
            total_sections=len(all_sections),
            total_words=total_words,
        )

        return all_sections
