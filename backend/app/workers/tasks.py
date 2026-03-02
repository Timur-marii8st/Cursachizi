"""arq worker task definitions for pipeline execution."""

import io
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.api.deps import get_llm_provider, get_search_provider
from backend.app.models.job import Job
from backend.app.pipeline.orchestrator import PipelineOrchestrator, StageCallback
from shared.schemas.job import JobStage, JobStatus
from shared.schemas.pipeline import PipelineConfig

logger = structlog.get_logger()


class JobProgressCallback(StageCallback):
    """Updates job progress in the database as pipeline stages execute."""

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id

    async def on_stage_start(self, stage: str, message: str = "") -> None:
        await self._update_job(stage=stage, message=message)

    async def on_stage_progress(
        self, stage: str, progress_pct: int, message: str = ""
    ) -> None:
        await self._update_job(stage=stage, progress_pct=progress_pct, message=message)

    async def on_stage_complete(self, stage: str, message: str = "") -> None:
        await self._update_job(stage=stage, message=message)

    async def _update_job(
        self,
        stage: str = "",
        progress_pct: int | None = None,
        message: str = "",
    ) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, self._job_id)
            if not job:
                return
            if stage:
                job.stage = stage
            if progress_pct is not None:
                job.progress_pct = progress_pct
            if message:
                job.stage_message = message
            job.updated_at = datetime.utcnow()
            await session.commit()


async def run_pipeline(ctx: dict, job_id: str) -> str:
    """Main worker task: execute the full pipeline for a job.

    This is the entry point called by arq when a job is dequeued.
    """
    settings = get_settings()
    logger.info("pipeline_worker_start", job_id=job_id)

    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if not job:
            logger.error("job_not_found", job_id=job_id)
            return f"Job {job_id} not found"

        # Mark as running
        job.status = JobStatus.RUNNING
        job.stage = JobStage.RESEARCHING
        job.updated_at = datetime.utcnow()
        await session.commit()

    try:
        llm = get_llm_provider(settings)
        search = get_search_provider(settings)

        orchestrator = PipelineOrchestrator(llm=llm, search=search)
        callback = JobProgressCallback(job_id)

        config = PipelineConfig(
            max_search_results=settings.max_search_results,
            max_sources=settings.max_sources_per_topic,
            max_tokens_per_section=settings.max_tokens_per_section,
            writer_model=settings.default_writer_model,
            light_model=settings.default_light_model,
            timeout_seconds=settings.pipeline_timeout_seconds,
        )

        result = await orchestrator.run(
            topic=job.topic,
            discipline=job.discipline,
            university=job.university,
            page_count=job.page_count,
            additional_instructions=job.additional_instructions,
            config=config,
            callback=callback,
        )

        # Save results
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if not job:
                return f"Job {job_id} disappeared"

            job.status = JobStatus.COMPLETED
            job.stage = JobStage.FINALIZING
            job.progress_pct = 100
            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()

            # Store pipeline data
            if result.research:
                job.research_data = result.research.model_dump()
            if result.outline:
                job.outline_data = result.outline.model_dump()
            if result.fact_check:
                job.fact_check_data = result.fact_check.model_dump()

            # TODO: Upload document to S3 and set document_url
            # For MVP, we'll store a flag that document is ready
            if result.document_bytes:
                job.stage_message = f"Документ готов ({len(result.document_bytes) // 1024} КБ)"

            await session.commit()

        logger.info("pipeline_worker_complete", job_id=job_id)
        return f"Job {job_id} completed successfully"

    except Exception as e:
        logger.error("pipeline_worker_failed", job_id=job_id, error=str(e))

        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)[:2000]
                job.updated_at = datetime.utcnow()
                await session.commit()

        return f"Job {job_id} failed: {e}"


class WorkerSettings:
    """arq worker configuration."""

    functions = [run_pipeline]
    redis_settings = None  # Set from environment at startup

    @staticmethod
    def on_startup(ctx: dict) -> None:
        logger.info("arq_worker_started")

    @staticmethod
    def on_shutdown(ctx: dict) -> None:
        logger.info("arq_worker_stopped")

    max_jobs = 3
    job_timeout = 1200  # 20 minutes max per job
    retry_jobs = False  # Don't auto-retry; let the user retry manually
