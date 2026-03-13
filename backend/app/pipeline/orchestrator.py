"""Pipeline orchestrator — runs all stages end-to-end for a single job."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from backend.app.llm.openrouter import OpenRouterProvider
from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.formatter.article_docx_generator import ArticleDocxGenerator
from backend.app.pipeline.formatter.document_renderer import DocumentRenderer
from backend.app.pipeline.formatter.stage import FormatterStage
from backend.app.pipeline.formatter.visual_matcher import VisualTemplateMatcher
from backend.app.pipeline.research.diversity_checker import SourceDiversityChecker
from backend.app.pipeline.research.searcher import SearchProvider
from backend.app.pipeline.research.stage import ResearchStage
from backend.app.pipeline.verifier.correction_applier import CorrectionApplier
from backend.app.pipeline.verifier.stage import VerifierStage
from backend.app.pipeline.writer.article_stage import ArticleWriterStage
from backend.app.pipeline.writer.citation_fixer import fix_citations
from backend.app.pipeline.writer.coherence_checker import CoherenceChecker
from backend.app.pipeline.writer.humanizer import Humanizer, TranslationProvider
from backend.app.pipeline.writer.intro_conclusion_validator import IntroductionConclusionValidator
from backend.app.pipeline.writer.section_evaluator import SectionEvaluator
from backend.app.pipeline.writer.stage import WriterStage
from shared.schemas.job import WorkType
from shared.schemas.pipeline import (
    CHAPTER_CONCLUSION,
    CHAPTER_INTRO,
    BibliographyRegistry,
    CoherenceResult,
    FactCheckResult,
    Outline,
    PipelineConfig,
    ResearchResult,
    SectionContent,
    VisualMatchResult,
)
from shared.schemas.template import GostTemplate

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    """Complete result of a pipeline execution."""

    outline: Outline | None = None
    research: ResearchResult | None = None
    bibliography: BibliographyRegistry | None = None
    sections: list[SectionContent] = field(default_factory=list)
    coherence: CoherenceResult | None = None
    fact_check: FactCheckResult | None = None
    document_bytes: bytes | None = None
    visual_match_results: list[VisualMatchResult] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class StageCallback:
    """Callback interface for reporting pipeline progress."""

    async def on_stage_start(self, stage: str, message: str = "") -> None:
        pass

    async def on_stage_progress(
        self, stage: str, progress_pct: int, message: str = ""
    ) -> None:
        pass

    async def on_stage_complete(self, stage: str, message: str = "") -> None:
        pass


class PipelineOrchestrator:
    """Runs the complete coursework generation pipeline.

    Stages:
    1. Research — query expansion, search, scraping, ranking
    2. Outline — generate coursework structure
    3. Write — section-by-section content generation
    4. Verify — fact-check claims
    5. Format — generate ГОСТ-compliant .docx
    6. Visual Match — iterative format comparison with reference (optional)
    """

    def __init__(
        self,
        llm: LLMProvider,
        search: SearchProvider,
        template: GostTemplate | None = None,
        vision_llm: OpenRouterProvider | None = None,
        translator: TranslationProvider | None = None,
    ) -> None:
        self._llm = llm
        self._search = search
        self._research_stage = ResearchStage(llm, search)
        self._diversity_checker = SourceDiversityChecker(search=search)
        self._writer_stage = WriterStage(llm)
        self._article_writer_stage = ArticleWriterStage(llm)
        self._section_evaluator = SectionEvaluator(llm)
        self._coherence_checker = CoherenceChecker(llm)
        self._intro_validator = IntroductionConclusionValidator(llm)
        self._humanizer = Humanizer(llm, translator) if translator else None
        self._verifier_stage = VerifierStage(llm, search)
        self._correction_applier = CorrectionApplier(llm)
        self._formatter_stage = FormatterStage(template)
        self._article_docx_generator = ArticleDocxGenerator(template)
        self._template = template or GostTemplate()
        self._vision_llm = vision_llm

    async def run(
        self,
        topic: str,
        discipline: str = "",
        university: str = "",
        page_count: int = 30,
        additional_instructions: str = "",
        work_type: str = "coursework",
        config: PipelineConfig | None = None,
        callback: StageCallback | None = None,
        reference_docx_bytes: bytes | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            topic: Work topic.
            discipline: Academic discipline.
            university: University name.
            page_count: Target page count.
            additional_instructions: Extra user instructions.
            work_type: Type of work — "coursework" or "article".
            config: Pipeline configuration overrides.
            callback: Optional progress callback.

        Returns:
            PipelineResult with all outputs.
        """
        config = config or PipelineConfig()
        callback = callback or StageCallback()
        result = PipelineResult(started_at=datetime.now(UTC))

        try:
            # Stage 1: Research
            await callback.on_stage_start("researching", "Исследуем тему...")
            result.research = await self._research_stage.run(
                topic=topic,
                discipline=discipline,
                config=config,
            )
            # Stage 1b: Source diversity check
            diversity_report = self._diversity_checker.analyze(result.research.sources)
            if not diversity_report.is_sufficient:
                result.research.sources = await self._diversity_checker.improve(
                    sources=result.research.sources,
                    topic=topic,
                    report=diversity_report,
                )

            # Build unified bibliography registry from real research sources
            result.bibliography = BibliographyRegistry.from_sources(
                result.research.sources
            )
            if len(result.research.sources) == 0:
                logger.error("research_returned_no_sources", topic=topic[:80])
            elif len(result.research.sources) < 3:
                logger.warning(
                    "research_few_sources",
                    count=len(result.research.sources),
                    topic=topic[:80],
                )

            await callback.on_stage_complete(
                "researching",
                f"Найдено {len(result.research.sources)} источников "
                f"({diversity_report.academic_count} академ., "
                f"{diversity_report.unique_domains} доменов)",
            )

            # Select writer stage based on work type
            is_article = work_type == WorkType.ARTICLE
            writer_stage = self._article_writer_stage if is_article else self._writer_stage
            work_label = "статьи" if is_article else "курсовой"

            # Stage 2: Outline
            await callback.on_stage_start("outlining", f"Составляем план {work_label}...")
            result.outline = await writer_stage.generate_outline(
                topic=topic,
                discipline=discipline,
                page_count=page_count,
                research=result.research,
                config=config,
            )
            section_label = "разделов" if is_article else "глав"
            await callback.on_stage_complete(
                "outlining",
                f"План: {len(result.outline.chapters)} {section_label}",
            )

            # Stage 3: Write
            await callback.on_stage_start("writing", f"Пишем текст {work_label}...")

            async def write_progress(done: int, total: int) -> None:
                pct = int(done / total * 100) if total > 0 else 0
                await callback.on_stage_progress(
                    "writing", pct, f"Написано {done}/{total} разделов"
                )

            result.sections = await writer_stage.write_all_sections(
                topic=topic,
                discipline=discipline,
                page_count=page_count,
                outline=result.outline,
                research=result.research,
                additional_instructions=additional_instructions,
                config=config,
                progress_callback=write_progress,
                bibliography=result.bibliography,
            )
            total_words = sum(s.word_count for s in result.sections)
            await callback.on_stage_complete(
                "writing",
                f"Написано {total_words} слов в {len(result.sections)} разделах",
            )

            # Stage 3b: Section quality evaluation + rewrite loop
            if config.enable_section_rewrite:
                await callback.on_stage_start(
                    "writing", "Оцениваем качество разделов..."
                )
                result.sections = await self._evaluate_and_rewrite_sections(
                    sections=result.sections,
                    outline=result.outline,
                    research=result.research,
                    page_count=page_count,
                    config=config,
                    callback=callback,
                    bibliography=result.bibliography,
                )
                total_words = sum(s.word_count for s in result.sections)

            # Stage 3b½: Introduction/conclusion structural validation (coursework only)
            if not is_article:
                result.sections = await self._validate_intro_conclusion(
                    sections=result.sections,
                    topic=topic,
                    discipline=discipline,
                    outline=result.outline,
                    config=config,
                    callback=callback,
                )

            # Stage 3c: Cross-section coherence check
            if config.enable_coherence_check:
                await callback.on_stage_start(
                    "writing", "Проверяем связность разделов..."
                )
                coherence = await self._coherence_checker.check(
                    sections=result.sections,
                    model=config.light_model,
                )
                if coherence.issues:
                    result.sections, coherence = await self._coherence_checker.fix(
                        sections=result.sections,
                        coherence_result=coherence,
                        model=config.writer_model,
                    )
                result.coherence = coherence
                await callback.on_stage_progress(
                    "writing",
                    100,
                    f"Связность: найдено {coherence.issues_found} замечаний, "
                    f"исправлено {coherence.fixes_applied}",
                )

            # Stage 3d: Humanizer (translation cycling)
            if config.enable_humanizer and self._humanizer:
                await callback.on_stage_start(
                    "writing", "Гуманизация текста через перевод..."
                )
                result.sections = await self._humanizer.humanize_all(
                    sections=result.sections,
                    model=config.writer_model,
                )
                total_words = sum(s.word_count for s in result.sections)
                await callback.on_stage_progress(
                    "writing", 100, "Гуманизация завершена"
                )

            # Stage 4: Fact-check
            if config.enable_fact_check:
                await callback.on_stage_start("fact_checking", "Проверяем факты...")

                async def fc_progress(done: int, total: int) -> None:
                    pct = int(done / total * 100) if total > 0 else 0
                    await callback.on_stage_progress(
                        "fact_checking", pct, f"Проверено {done}/{total} утверждений"
                    )

                result.fact_check = await self._verifier_stage.run(
                    sections=result.sections,
                    config=config,
                    progress_callback=fc_progress,
                )
                await callback.on_stage_complete(
                    "fact_checking",
                    f"Проверено {result.fact_check.checked_claims} утверждений, "
                    f"{result.fact_check.unsupported} не подтверждено",
                )

                # Stage 4b: Apply corrections for unsupported claims
                if result.fact_check.unsupported > 0:
                    await callback.on_stage_start(
                        "fact_checking", "Исправляем неточности в тексте..."
                    )
                    result.sections, corrections_applied = (
                        await self._correction_applier.apply_corrections(
                            sections=result.sections,
                            fact_check=result.fact_check,
                            model=config.writer_model,
                        )
                    )
                    result.fact_check.corrections_applied = corrections_applied
                    await callback.on_stage_complete(
                        "fact_checking",
                        f"Исправлено {corrections_applied} неточностей",
                    )

            # Stage 4c: Fix citations — remap LLM-generated [N] to real registry numbers
            if result.bibliography and result.bibliography.entries:
                await callback.on_stage_progress(
                    "formatting", 0, "Исправляем ссылки на источники..."
                )
                result.sections = fix_citations(
                    result.sections, result.bibliography
                )
                # Validate after fixing
                invalid_total = 0
                for section in result.sections:
                    invalid = result.bibliography.validate_citations(section.content)
                    if invalid:
                        invalid_total += len(invalid)
                if invalid_total > 0:
                    logger.warning(
                        "citations_still_invalid_after_fix",
                        invalid_total=invalid_total,
                        registry_size=len(result.bibliography.entries),
                    )
                total_words = sum(s.word_count for s in result.sections)

            # Stage 5: Format
            await callback.on_stage_start("formatting", "Форматируем документ...")
            logger.info(
                "pre_format_check",
                has_bibliography=result.bibliography is not None,
                bibliography_entries=len(result.bibliography.entries) if result.bibliography else 0,
                sections_count=len(result.sections),
                sources_count=len(result.research.sources),
            )
            if is_article:
                result.document_bytes = self._article_docx_generator.generate(
                    outline=result.outline,
                    sections=result.sections,
                    sources=result.research.sources,
                    fact_check=result.fact_check,
                    university=university,
                    discipline=discipline,
                    bibliography=result.bibliography,
                )
            else:
                result.document_bytes = self._formatter_stage.run(
                    outline=result.outline,
                    sections=result.sections,
                    sources=result.research.sources,
                    fact_check=result.fact_check,
                    university=university,
                    discipline=discipline,
                    bibliography=result.bibliography,
                )
            await callback.on_stage_complete(
                "formatting",
                f"Документ готов ({len(result.document_bytes) // 1024} КБ)",
            )

            # Stage 6: Visual template matching (optional)
            if (
                config.enable_visual_match
                and reference_docx_bytes
                and self._vision_llm
            ):
                await callback.on_stage_start(
                    "visual_matching",
                    "Сравниваем форматирование с образцом...",
                )

                renderer = DocumentRenderer()
                matcher = VisualTemplateMatcher(
                    vision_llm=self._vision_llm,
                    renderer=renderer,
                    vision_model=config.vision_model,
                )

                # Analyze reference formatting first
                ref_template = await matcher.analyze_reference(reference_docx_bytes)
                await callback.on_stage_progress(
                    "visual_matching", 20, "Шаблон образца извлечён"
                )

                # Iteratively match
                (
                    result.document_bytes,
                    _final_template,
                    result.visual_match_results,
                ) = await matcher.match_iteratively(
                    reference_docx_bytes=reference_docx_bytes,
                    outline=result.outline,
                    sections=result.sections,
                    sources=result.research.sources,
                    initial_template=ref_template,
                    max_iterations=config.visual_match_max_iterations,
                    university=university,
                    discipline=discipline,
                    bibliography=result.bibliography,
                )

                iterations_done = len(result.visual_match_results)
                final_score = (
                    result.visual_match_results[-1].score
                    if result.visual_match_results
                    else 0
                )
                await callback.on_stage_complete(
                    "visual_matching",
                    f"{iterations_done} итераций, оценка {final_score:.1f}/10",
                )

            result.completed_at = datetime.now(UTC)
            logger.info(
                "pipeline_complete",
                topic=topic[:80],
                sections=len(result.sections),
                words=total_words,
                sources=len(result.research.sources),
                visual_match=bool(result.visual_match_results),
            )

        except Exception as e:
            result.error = str(e)
            logger.error(
                "pipeline_failed",
                topic=topic[:80],
                error=str(e),
                exc_type=type(e).__name__,
                exc_info=True,
            )
            raise

        return result

    async def _evaluate_and_rewrite_sections(
        self,
        sections: list[SectionContent],
        outline: Outline,
        research: ResearchResult,
        page_count: int,
        config: PipelineConfig,
        callback: StageCallback,
        bibliography: BibliographyRegistry | None = None,
    ) -> list[SectionContent]:
        """Evaluate each section and rewrite those that fail quality checks."""
        body_pages = page_count - 4  # Minus intro/conclusion/title/toc
        total_subsections = sum(
            max(len(ch.subsections), 1) for ch in outline.chapters
        )
        target_words_per_section = (body_pages * 250) // max(total_subsections, 1)
        chapters_map = {ch.number: ch for ch in outline.chapters}
        updated = list(sections)

        rewrites_total = 0
        for i, section in enumerate(updated):
            evaluation = self._section_evaluator.evaluate(
                section=section,
                target_words=target_words_per_section,
                min_citations=config.min_citations_per_section,
                previous_sections=updated[:i],
            )

            if evaluation.passed:
                continue

            chapter = chapters_map.get(section.chapter_number)
            if not chapter:
                continue

            # Rewrite loop (max attempts from config)
            for attempt in range(config.max_section_rewrites):
                rewritten = await self._section_evaluator.rewrite(
                    section=section,
                    evaluation=evaluation,
                    chapter=chapter,
                    sources=research.sources,
                    target_words=target_words_per_section,
                    model=config.writer_model,
                    bibliography=bibliography,
                )

                evaluation = self._section_evaluator.evaluate(
                    section=rewritten,
                    target_words=target_words_per_section,
                    min_citations=config.min_citations_per_section,
                    previous_sections=updated[:i],
                )
                evaluation.rewrite_count = attempt + 1
                updated[i] = rewritten
                section = rewritten
                rewrites_total += 1

                if evaluation.passed:
                    break

            logger.info(
                "section_eval_complete",
                section=section.section_title[:50],
                passed=evaluation.passed,
                rewrites=evaluation.rewrite_count,
            )

        if rewrites_total > 0:
            await callback.on_stage_progress(
                "writing", 100, f"Переписано {rewrites_total} разделов"
            )

        return updated

    async def _validate_intro_conclusion(
        self,
        sections: list[SectionContent],
        topic: str,
        discipline: str,
        outline: Outline,
        config: PipelineConfig,
        callback: StageCallback,
    ) -> list[SectionContent]:
        """Validate and fix introduction/conclusion structural elements."""
        updated = list(sections)

        for i, section in enumerate(updated):
            # Check introduction
            if section.chapter_number == CHAPTER_INTRO:
                missing = self._intro_validator.check_introduction(section)
                if missing:
                    await callback.on_stage_progress(
                        "writing", 95,
                        f"Введение: добавляем {', '.join(missing)}",
                    )
                    updated[i] = await self._intro_validator.fix_introduction(
                        section=section,
                        missing_elements=missing,
                        topic=topic,
                        discipline=discipline,
                        outline=outline,
                        model=config.writer_model,
                    )

            # Check conclusion
            elif section.chapter_number == CHAPTER_CONCLUSION:
                intro = next(
                    (s for s in updated if s.chapter_number == 0), None
                )
                if intro:
                    issues = self._intro_validator.check_conclusion(
                        conclusion=section, introduction=intro
                    )
                    if issues:
                        # TODO: IntroductionConclusionValidator has no fix_conclusion method.
                        # A fix_conclusion equivalent should be implemented mirroring
                        # fix_introduction, and called here as:
                        #   updated[i] = await self._intro_validator.fix_conclusion(
                        #       section=section, issues=issues, topic=topic,
                        #       discipline=discipline, outline=outline,
                        #       model=config.writer_model,
                        #   )
                        logger.warning(
                            "conclusion_issues_found_unfixed",
                            issues=issues,
                        )

        return updated
