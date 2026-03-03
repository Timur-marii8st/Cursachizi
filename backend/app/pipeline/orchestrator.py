"""Pipeline orchestrator — runs all stages end-to-end for a single job."""

from dataclasses import dataclass, field
from datetime import datetime

import structlog

from backend.app.llm.openrouter import OpenRouterProvider
from backend.app.llm.provider import LLMProvider
from backend.app.pipeline.formatter.document_renderer import DocumentRenderer
from backend.app.pipeline.formatter.stage import FormatterStage
from backend.app.pipeline.formatter.visual_matcher import VisualTemplateMatcher
from backend.app.pipeline.research.searcher import SearchProvider
from backend.app.pipeline.research.stage import ResearchStage
from backend.app.pipeline.verifier.stage import VerifierStage
from backend.app.pipeline.writer.stage import WriterStage
from shared.schemas.pipeline import (
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
    sections: list[SectionContent] = field(default_factory=list)
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
    ) -> None:
        self._llm = llm
        self._research_stage = ResearchStage(llm, search)
        self._writer_stage = WriterStage(llm)
        self._verifier_stage = VerifierStage(llm, search)
        self._formatter_stage = FormatterStage(template)
        self._template = template or GostTemplate()
        self._vision_llm = vision_llm

    async def run(
        self,
        topic: str,
        discipline: str = "",
        university: str = "",
        page_count: int = 30,
        additional_instructions: str = "",
        config: PipelineConfig | None = None,
        callback: StageCallback | None = None,
        reference_docx_bytes: bytes | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline.

        Args:
            topic: Coursework topic.
            discipline: Academic discipline.
            university: University name.
            page_count: Target page count.
            additional_instructions: Extra user instructions.
            config: Pipeline configuration overrides.
            callback: Optional progress callback.

        Returns:
            PipelineResult with all outputs.
        """
        config = config or PipelineConfig()
        callback = callback or StageCallback()
        result = PipelineResult(started_at=datetime.utcnow())

        try:
            # Stage 1: Research
            await callback.on_stage_start("researching", "Исследуем тему...")
            result.research = await self._research_stage.run(
                topic=topic,
                discipline=discipline,
                config=config,
            )
            await callback.on_stage_complete(
                "researching",
                f"Найдено {len(result.research.sources)} источников",
            )

            # Stage 2: Outline
            await callback.on_stage_start("outlining", "Составляем план...")
            result.outline = await self._writer_stage.generate_outline(
                topic=topic,
                discipline=discipline,
                page_count=page_count,
                research=result.research,
                config=config,
            )
            await callback.on_stage_complete(
                "outlining",
                f"План: {len(result.outline.chapters)} глав",
            )

            # Stage 3: Write
            await callback.on_stage_start("writing", "Пишем текст...")

            async def write_progress(done: int, total: int) -> None:
                pct = int(done / total * 100) if total > 0 else 0
                await callback.on_stage_progress(
                    "writing", pct, f"Написано {done}/{total} разделов"
                )

            result.sections = await self._writer_stage.write_all_sections(
                topic=topic,
                discipline=discipline,
                page_count=page_count,
                outline=result.outline,
                research=result.research,
                additional_instructions=additional_instructions,
                config=config,
                progress_callback=write_progress,
            )
            total_words = sum(s.word_count for s in result.sections)
            await callback.on_stage_complete(
                "writing",
                f"Написано {total_words} слов в {len(result.sections)} разделах",
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

            # Stage 5: Format
            await callback.on_stage_start("formatting", "Форматируем документ...")
            result.document_bytes = self._formatter_stage.run(
                outline=result.outline,
                sections=result.sections,
                sources=result.research.sources,
                fact_check=result.fact_check,
                university=university,
                discipline=discipline,
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

            result.completed_at = datetime.utcnow()
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
            logger.error("pipeline_failed", topic=topic[:80], error=str(e))
            raise

        return result
