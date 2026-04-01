"""arq worker task definitions for pipeline execution."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import structlog
from arq.connections import RedisSettings
from botocore.exceptions import ClientError
from sqlalchemy import update as sql_update

from backend.app.api.deps import get_llm_provider, get_search_provider, get_vision_llm_provider
from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.job import Job
from backend.app.pipeline.orchestrator import PipelineOrchestrator, StageCallback
from backend.app.services.storage import (
    download_document,
    ensure_bucket,
    upload_document,
)
from shared.schemas.job import JobStage, JobStatus
from shared.schemas.pipeline import PipelineConfig

logger = structlog.get_logger()

# Transient-error retry configuration
_PIPELINE_MAX_RETRIES = 3
_PIPELINE_RETRY_BASE_DELAY = 2.0  # seconds; delay = base ** (attempt + 1) → 2, 4, 8

# Exception types that indicate a transient failure worth retrying
_TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    asyncio.TimeoutError,
    TimeoutError,
)


def _format_worker_error(exc: Exception, *, timeout_seconds: int | None = None) -> str:
    """Convert exceptions into a stable, user-facing error message."""
    message = str(exc).strip()
    if message:
        return message
    if isinstance(exc, TimeoutError):
        if timeout_seconds is not None:
            return f"Pipeline timed out after {timeout_seconds} seconds"
        return "Pipeline timed out"
    return exc.__class__.__name__


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
            job.updated_at = datetime.now(UTC)
            await session.commit()


async def run_pipeline(ctx: dict, job_id: str) -> str:
    """Main worker task: execute the full pipeline for a job.

    This is the entry point called by arq when a job is dequeued.
    """
    settings = get_settings()
    timeout_seconds = settings.pipeline_timeout_seconds
    logger.info("pipeline_worker_start", job_id=job_id)

    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if not job:
            logger.error("job_not_found", job_id=job_id)
            return f"Job {job_id} not found"

        job.status = JobStatus.RUNNING
        job.stage = JobStage.RESEARCHING
        job.updated_at = datetime.now(UTC)
        await session.commit()

        work_type = job.work_type
        logger.info(
            "pipeline_worker_job_loaded",
            job_id=job_id,
            work_type=work_type,
            topic=job.topic[:80],
        )
        topic = job.topic
        discipline = job.discipline
        university = job.university
        page_count = job.page_count
        additional_instructions = job.additional_instructions
        reference_s3_key = job.reference_s3_key
        job_pipeline_config = job.pipeline_config if isinstance(job.pipeline_config, dict) else {}
        custom_outline = job_pipeline_config.get("custom_outline", "")

    # ARCH-001: enforce pipeline timeout to prevent indefinite worker blocking
    timeout_seconds = settings.pipeline_timeout_seconds

    # Resolve reference document once — outside the retry loop, since it comes
    # from S3 (stable) and we don't want to re-download it on every attempt.
    reference_docx_bytes = None
    if reference_s3_key:
        try:
            reference_docx_bytes = await asyncio.to_thread(
                download_document,
                endpoint_url=settings.s3_endpoint_url,
                region=settings.s3_region,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                bucket=settings.s3_bucket_name,
                object_key=reference_s3_key,
            )
        except ClientError as e:
            logger.error("reference_download_failed", key=reference_s3_key, error=str(e))

    # Build pipeline config once — it is stateless and attempt-independent.
    # Read user-selected source count from job, fallback to global setting
    user_max_sources = job_pipeline_config.get("max_sources", settings.max_sources_per_topic)

    visual_match_enabled = settings.visual_match_enabled and bool(reference_s3_key)

    config = PipelineConfig(
        max_search_results=max(settings.max_search_results, user_max_sources * 2),
        max_sources=user_max_sources,
        max_tokens_per_section=settings.max_tokens_per_section,
        writer_model=settings.default_writer_model,
        light_model=settings.default_light_model,
        timeout_seconds=settings.pipeline_timeout_seconds,
        enable_visual_match=visual_match_enabled,
    )
    timeout_seconds = config.timeout_seconds or settings.pipeline_timeout_seconds

    last_error: Exception | None = None

    for attempt in range(_PIPELINE_MAX_RETRIES):
        # Providers hold open HTTP connections and must be created fresh for each
        # attempt; the finally block below closes them after every attempt.
        llm = get_llm_provider(settings)
        search = get_search_provider(settings)

        # Optional: translation provider for humanizer
        translator = None
        if settings.google_translate_api_key:
            from backend.app.pipeline.writer.humanizer import GoogleTranslateProvider
            translator = GoogleTranslateProvider(api_key=settings.google_translate_api_key)
        elif settings.deepl_api_key:
            from backend.app.pipeline.writer.humanizer import DeepLTranslateProvider
            translator = DeepLTranslateProvider(api_key=settings.deepl_api_key)

        vision_llm = get_vision_llm_provider(settings) if visual_match_enabled else None
        _effective_reference = reference_docx_bytes

        orchestrator = PipelineOrchestrator(
            llm=llm, search=search, translator=translator,
            vision_llm=vision_llm,
        )
        callback = JobProgressCallback(job_id)

        try:
            result = await asyncio.wait_for(
                orchestrator.run(
                    topic=topic,
                    discipline=discipline,
                    university=university,
                    page_count=page_count,
                    additional_instructions=additional_instructions,
                    work_type=work_type,
                    config=config,
                    callback=callback,
                    reference_docx_bytes=_effective_reference,
                    custom_outline=custom_outline,
                ),
                timeout=timeout_seconds,
            )

            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if not job:
                    return f"Job {job_id} disappeared"

                # BUG-002: respect cancellation that happened during pipeline execution
                if job.status == JobStatus.CANCELLED:
                    logger.info("pipeline_worker_job_cancelled", job_id=job_id)
                    return f"Job {job_id} was cancelled before completion"

                job.status = JobStatus.COMPLETED
                job.stage = JobStage.FINALIZING
                job.progress_pct = 100
                job.completed_at = datetime.now(UTC)
                job.updated_at = datetime.now(UTC)

                if result.research:
                    job.research_data = result.research.model_dump()
                if result.outline:
                    job.outline_data = result.outline.model_dump()
                if result.fact_check:
                    job.fact_check_data = result.fact_check.model_dump()

                if result.document_bytes:
                    document_key = f"jobs/{job_id}/{uuid4()}.docx"
                    # ARCH-002: ensure bucket + upload via consolidated storage module
                    await asyncio.to_thread(
                        ensure_bucket,
                        endpoint_url=settings.s3_endpoint_url,
                        region=settings.s3_region,
                        access_key=settings.s3_access_key,
                        secret_key=settings.s3_secret_key,
                        bucket=settings.s3_bucket_name,
                    )
                    await asyncio.to_thread(
                        upload_document,
                        endpoint_url=settings.s3_endpoint_url,
                        region=settings.s3_region,
                        access_key=settings.s3_access_key,
                        secret_key=settings.s3_secret_key,
                        bucket=settings.s3_bucket_name,
                        object_key=document_key,
                        document_bytes=result.document_bytes,
                    )
                    job.document_s3_key = document_key
                    # Use backend API download URL instead of internal MinIO presigned URL.
                    # MinIO is not exposed externally; the backend proxies the download.
                    job.document_url = f"{settings.api_base_url}/api/jobs/{job_id}/download"
                    job.stage_message = f"Document ready ({len(result.document_bytes) // 1024} KB)"

                await session.commit()

            logger.info("pipeline_worker_complete", job_id=job_id, attempt=attempt + 1)
            return f"Job {job_id} completed successfully"

        except _TRANSIENT_EXCEPTIONS as e:
            last_error = e
            if attempt < _PIPELINE_MAX_RETRIES - 1:
                delay = _PIPELINE_RETRY_BASE_DELAY ** (attempt + 1)
                logger.warning(
                    "pipeline_worker_transient_error_retry",
                    job_id=job_id,
                    attempt=attempt + 1,
                    max_retries=_PIPELINE_MAX_RETRIES,
                    error_type=e.__class__.__name__,
                    error=str(e),
                    retry_in_seconds=delay,
                )
                # Job stays RUNNING during retries — do NOT set status to FAILED here.
            else:
                logger.error(
                    "pipeline_worker_transient_error_exhausted",
                    job_id=job_id,
                    attempt=attempt + 1,
                    error_type=e.__class__.__name__,
                    error=str(e),
                )

        except Exception as e:
            # Non-transient error (programming error, validation failure, etc.) —
            # do not retry; break immediately to permanent-failure handling.
            last_error = e
            logger.error(
                "pipeline_worker_non_transient_error",
                job_id=job_id,
                attempt=attempt + 1,
                error_type=e.__class__.__name__,
                error=str(e),
            )
            break

        finally:
            # FIX-002: close all provider clients to prevent TCP connection leaks.
            # Runs after every attempt (success, transient failure, or hard failure).
            if hasattr(llm, "aclose"):
                await llm.aclose()
            if vision_llm is not None and hasattr(vision_llm, "aclose"):
                await vision_llm.aclose()
            if hasattr(search, "aclose"):
                await search.aclose()
            if translator is not None and hasattr(translator, "aclose"):
                await translator.aclose()

        # Only reached on transient error with retries remaining — sleep then loop.
        if attempt < _PIPELINE_MAX_RETRIES - 1:
            await asyncio.sleep(_PIPELINE_RETRY_BASE_DELAY ** (attempt + 1))

    # ------------------------------------------------------------------ #
    # All attempts exhausted — mark job as permanently failed.            #
    # ------------------------------------------------------------------ #
    assert last_error is not None  # loop always sets this before reaching here

    if isinstance(last_error, (TimeoutError, asyncio.TimeoutError)):
        logger.error(
            "pipeline_worker_timed_out",
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            exc_info=True,
        )
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            stage = job.stage if job else ""
            stage_message = job.stage_message if job else ""

            error_message = f"Pipeline timed out after {timeout_seconds} seconds"
            if stage:
                error_message += f" during stage '{stage}'"
            if stage_message:
                error_message += f" ({stage_message})"

            if job:
                job.status = JobStatus.FAILED
                job.error_message = error_message[:2000]
                job.updated_at = datetime.now(UTC)
                await session.commit()

        return f"Job {job_id} failed: {error_message}"

    error_message = _format_worker_error(last_error, timeout_seconds=timeout_seconds)
    logger.error(
        "pipeline_worker_failed",
        job_id=job_id,
        error=error_message,
        error_type=last_error.__class__.__name__,
    )

    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job:
            job.status = JobStatus.FAILED
            job.error_message = error_message[:2000]
            job.updated_at = datetime.now(UTC)
            await session.commit()

    return f"Job {job_id} failed: {error_message}"


class WorkerSettings:
    """arq worker configuration."""

    functions = [run_pipeline]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        logger.info("arq_worker_started")
        cutoff = datetime.now(UTC) - timedelta(minutes=30)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                sql_update(Job)
                .where(Job.status == JobStatus.RUNNING, Job.updated_at < cutoff)
                .values(
                    status=JobStatus.FAILED,
                    error_message="Pipeline interrupted: worker restart",
                )
                .returning(Job.id)
            )
            stale_ids = [row[0] for row in result.fetchall()]
            await db.commit()

        if stale_ids:
            logger.warning("stale_jobs_cleaned_up", count=len(stale_ids), job_ids=stale_ids)
        else:
            logger.info("worker_startup_no_stale_jobs")

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        logger.info("arq_worker_stopped")

    max_jobs = 3
    job_timeout = 1200
    retry_jobs = False
