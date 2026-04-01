"""Complete writer stage for coursework generation."""

import asyncio
import re

import structlog

from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.writer.outliner import Outliner
from backend.app.pipeline.writer.section_writer import SectionWriter
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
        custom_outline: str = "",
    ) -> Outline:
        """Generate the coursework outline."""
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
        """Write all sections of the coursework."""
        config = config or PipelineConfig()
        model = config.writer_model
        all_sections: list[SectionContent] = []

        if bibliography is None:
            bibliography = BibliographyRegistry.from_sources(research.sources)
        logger.info("bibliography_registry_built", entries=len(bibliography.entries))

        total_sections = 2
        for ch in outline.chapters:
            total_sections += max(len(ch.subsections), 1)
        sections_done = 0

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

        body_pages = page_count - 4
        total_subsections = sum(max(len(ch.subsections), 1) for ch in outline.chapters)
        words_per_section = (body_pages * 250) // max(total_subsections, 1)

        body_section_titles: list[tuple[OutlineChapter, str]] = []
        for ch in outline.chapters:
            for st in (ch.subsections if ch.subsections else [ch.title]):
                body_section_titles.append((ch, st))

        source_assignments = self._assign_sources_to_sections(
            bibliography, len(body_section_titles)
        )
        section_briefs = self._build_section_briefs(outline)

        write_tasks_meta: list[tuple[OutlineChapter, str, list[int], SectionBrief]] = []
        body_idx = 0
        for chapter in outline.chapters:
            logger.info("writing_chapter", chapter=chapter.number, title=chapter.title[:50])
            sections_to_write = chapter.subsections if chapter.subsections else [chapter.title]
            for section_title in sections_to_write:
                required_nums = (
                    source_assignments[body_idx] if body_idx < len(source_assignments) else []
                )
                brief = section_briefs[(chapter.number, section_title)]
                body_idx += 1
                write_tasks_meta.append((chapter, section_title, required_nums, brief))

        previous_sections_snapshot = list(all_sections)
        semaphore = asyncio.Semaphore(3)
        progress_lock = asyncio.Lock()

        async def write_one_section(
            chapter: OutlineChapter,
            section_title: str,
            required_nums: list[int],
            brief: SectionBrief,
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
                    section_brief=brief,
                )

        async def write_one_with_progress(
            chapter: OutlineChapter,
            section_title: str,
            required_nums: list[int],
            brief: SectionBrief,
        ) -> SectionContent:
            nonlocal sections_done
            section = await write_one_section(chapter, section_title, required_nums, brief)
            async with progress_lock:
                sections_done += 1
                done_snapshot = sections_done
            if progress_callback:
                await progress_callback(done_snapshot, total_sections)
            return section

        tasks = [
            write_one_with_progress(ch, st, rn, brief)
            for ch, st, rn, brief in write_tasks_meta
        ]
        body_results = await asyncio.gather(*tasks, return_exceptions=True)

        failures: list[str] = []
        for i, result in enumerate(body_results):
            if isinstance(result, Exception):
                ch, st, _, _ = write_tasks_meta[i]
                logger.error(
                    "section_write_failed",
                    chapter=ch.number,
                    section=st[:60],
                    error=str(result),
                )
                failures.append(f"{ch.number}:{st}")
            else:
                all_sections.append(result)

        if failures:
            raise RuntimeError(
                "Failed to write required sections: " + ", ".join(failures)
            )

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
        """Distribute bibliography entry numbers across body sections."""
        if not bibliography or not bibliography.entries or num_sections == 0:
            return [[] for _ in range(num_sections)]

        all_nums = [e.number for e in bibliography.entries]
        assignments: list[list[int]] = [[] for _ in range(num_sections)]

        for i, num in enumerate(all_nums):
            assignments[i % num_sections].append(num)

        min_per_section = min(3, len(all_nums))
        for assigned in assignments:
            while len(assigned) < min_per_section:
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

    @staticmethod
    def _build_section_briefs(outline: Outline) -> dict[tuple[int, str], SectionBrief]:
        """Build a structured writing contract for each body section."""
        briefs: dict[tuple[int, str], SectionBrief] = {}
        for chapter in outline.chapters:
            section_titles = chapter.subsections if chapter.subsections else [chapter.title]
            clean_titles = [WriterStage._clean_heading(title) for title in section_titles]
            total = len(section_titles)
            for index, section_title in enumerate(section_titles, start=1):
                clean_section = WriterStage._clean_heading(section_title)
                expected_topics = [clean_section]
                if chapter.title.strip() and chapter.title.strip() != clean_section:
                    expected_topics.append(chapter.title.strip())
                chapter_description = chapter.description.strip()
                section_summary = (
                    chapter_description
                    or f"Focus on the section topic '{clean_section}' within chapter '{chapter.title}'."
                )
                excluded_topics = [title for title in clean_titles if title != clean_section]
                briefs[(chapter.number, section_title)] = SectionBrief(
                    chapter_number=chapter.number,
                    chapter_title=chapter.title,
                    section_title=section_title,
                    chapter_description=chapter_description,
                    section_summary=section_summary,
                    expected_topics=expected_topics,
                    excluded_topics=excluded_topics,
                    section_position=index,
                    total_sections_in_chapter=total,
                )
        return briefs

    @staticmethod
    def _clean_heading(text: str) -> str:
        return re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text).strip()
