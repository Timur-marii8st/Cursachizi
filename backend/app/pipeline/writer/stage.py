"""Complete writer stage — generates all coursework content."""

import asyncio

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.writer.outliner import Outliner
from backend.app.pipeline.writer.section_writer import SectionWriter
from shared.schemas.pipeline import (
    BibliographyRegistry,
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
        bibliography: BibliographyRegistry | None = None,
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
            bibliography: Pre-built bibliography registry from orchestrator.

        Returns:
            List of all written sections in order.
        """
        config = config or PipelineConfig()
        model = config.writer_model
        all_sections: list[SectionContent] = []

        # Use provided registry or build from research sources
        if bibliography is None:
            bibliography = BibliographyRegistry.from_sources(research.sources)
        logger.info(
            "bibliography_registry_built",
            entries=len(bibliography.entries),
        )

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
            sources=research.sources,
            bibliography=bibliography,
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

        # Distribute bibliography entries across body sections so each section
        # cites DIFFERENT sources — this ensures broad source coverage (15-30).
        body_section_titles: list[tuple] = []  # (chapter, section_title)
        for ch in outline.chapters:
            for st in (ch.subsections if ch.subsections else [ch.title]):
                body_section_titles.append((ch, st))

        source_assignments = self._assign_sources_to_sections(
            bibliography, len(body_section_titles)
        )

        # Build the flat list of (chapter, section_title, required_nums) tasks
        # in order so that asyncio.gather preserves document order.
        write_tasks_meta: list[tuple] = []  # (chapter, section_title, required_nums)
        body_idx = 0
        for chapter in outline.chapters:
            logger.info("writing_chapter", chapter=chapter.number, title=chapter.title[:50])
            sections_to_write = chapter.subsections if chapter.subsections else [chapter.title]
            for section_title in sections_to_write:
                required_nums = source_assignments[body_idx] if body_idx < len(source_assignments) else []
                body_idx += 1
                write_tasks_meta.append((chapter, section_title, required_nums))

        # Snapshot of sections written so far (intro only) — used as coherence
        # context for all parallel body sections.  Each section sees the same
        # previous context; this is the correct trade-off when writing in
        # parallel (full sequential context is impossible without serialising).
        previous_sections_snapshot = list(all_sections)

        # Semaphore limits concurrent LLM calls to avoid provider rate limits.
        semaphore = asyncio.Semaphore(3)
        progress_lock = asyncio.Lock()

        async def write_one_section(
            chapter,
            section_title: str,
            required_nums: list[int],
        ) -> SectionContent:
            async with semaphore:
                return await self._section_writer.write_section(
                    paper_title=outline.title,
                    chapter=chapter,
                    section_title=section_title,
                    sources=research.sources,
                    previous_sections=previous_sections_snapshot,
                    target_words=words_per_section,
                    additional_instructions=additional_instructions,
                    model=model,
                    bibliography=bibliography,
                    required_source_nums=required_nums,
                )

        async def write_one_with_progress(
            chapter,
            section_title: str,
            required_nums: list[int],
        ) -> SectionContent:
            nonlocal sections_done
            section = await write_one_section(chapter, section_title, required_nums)
            async with progress_lock:
                sections_done += 1
                done_snapshot = sections_done
            if progress_callback:
                await progress_callback(done_snapshot, total_sections)
            return section

        tasks = [
            write_one_with_progress(ch, st, rn)
            for ch, st, rn in write_tasks_meta
        ]
        # gather preserves order; return_exceptions lets us handle partial failures
        body_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(body_results):
            if isinstance(result, Exception):
                ch, st, _ = write_tasks_meta[i]
                logger.error(
                    "section_write_failed",
                    chapter=ch.number,
                    section=st[:60],
                    error=str(result),
                )
            else:
                all_sections.append(result)

        # Step 3: Write conclusion
        logger.info("writing_conclusion")
        conclusion = await self._section_writer.write_conclusion(
            topic=topic,
            outline=outline,
            sections=all_sections,
            target_words=600,
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
            "writing_complete",
            total_sections=len(all_sections),
            total_words=total_words,
        )

        return all_sections

    @staticmethod
    def _assign_sources_to_sections(
        bibliography: BibliographyRegistry | None,
        num_sections: int,
    ) -> list[list[int]]:
        """Distribute bibliography entry numbers across body sections.

        Each section gets a unique slice of sources so that, collectively, all
        sections cover the entire registry. Sources are dealt round-robin and
        each section receives at least 3 required sources.
        """
        if not bibliography or not bibliography.entries or num_sections == 0:
            return [[] for _ in range(num_sections)]

        all_nums = [e.number for e in bibliography.entries]
        assignments: list[list[int]] = [[] for _ in range(num_sections)]

        # Round-robin deal: give each section its own slice
        for i, num in enumerate(all_nums):
            assignments[i % num_sections].append(num)

        # Ensure each section has at least 3 sources (wrap around if needed)
        min_per_section = min(3, len(all_nums))
        for _i, assigned in enumerate(assignments):
            while len(assigned) < min_per_section:
                # Add sources from the pool that aren't already assigned
                for num in all_nums:
                    if num not in assigned:
                        assigned.append(num)
                        break
                else:
                    break

        logger.info(
            "sources_distributed",
            total_sources=len(all_nums),
            sections=num_sections,
            per_section=[len(a) for a in assignments],
        )

        return assignments
