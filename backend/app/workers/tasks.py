"""arq worker task definitions for pipeline execution."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import boto3
import structlog
from arq.connections import RedisSettings
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import update as sql_update

from backend.app.api.deps import get_llm_provider, get_search_provider, get_vision_llm_provider
from backend.app.config import get_settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.models.job import Job
from backend.app.pipeline.orchestrator import PipelineOrchestrator, StageCallback
from shared.schemas.job import JobStage, JobStatus
from shared.schemas.pipeline import PipelineConfig

logger = structlog.get_logger()


def _upload_document_to_s3(
    *,
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_key: str,
    document_bytes: bytes,
) -> str:
    """Upload document bytes to S3 and return a pre-signed download URL."""
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            proxies={},  # bypass system proxy for local MinIO
        ),
    )

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)

    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=document_bytes,
        ContentType=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=7 * 24 * 60 * 60,
    )


def _download_from_s3(
    *,
    endpoint_url: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    object_key: str,
) -> bytes | None:
    """Download an object from S3 and return its bytes."""
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            proxies={},
        ),
    )

    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()
    except ClientError as e:
        logger.error("s3_download_failed", key=object_key, error=str(e))
        return None


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

    try:
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

        vision_llm = get_vision_llm_provider(settings)

        # Load reference docx for visual matching
        reference_docx_bytes = None
        if reference_s3_key:
            reference_docx_bytes = await asyncio.to_thread(
                _download_from_s3,
                endpoint_url=settings.s3_endpoint_url,
                region=settings.s3_region,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                bucket=settings.s3_bucket_name,
                object_key=reference_s3_key,
            )
        elif settings.visual_match_enabled and vision_llm:
            # Use default GOST reference
            from backend.app.pipeline.formatter.gost_reference import get_default_reference
            reference_docx_bytes = get_default_reference()

        orchestrator = PipelineOrchestrator(
            llm=llm, search=search, translator=translator,
            vision_llm=vision_llm,
        )
        callback = JobProgressCallback(job_id)

        config = PipelineConfig(
            max_search_results=settings.max_search_results,
            max_sources=settings.max_sources_per_topic,
            max_tokens_per_section=settings.max_tokens_per_section,
            writer_model=settings.default_writer_model,
            light_model=settings.default_light_model,
            timeout_seconds=settings.pipeline_timeout_seconds,
        )

        try:
            result = await orchestrator.run(
                topic=topic,
                discipline=discipline,
                university=university,
                page_count=page_count,
                additional_instructions=additional_instructions,
                work_type=work_type,
                config=config,
                callback=callback,
                reference_docx_bytes=reference_docx_bytes,
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
                    await asyncio.to_thread(
                        _upload_document_to_s3,
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

            logger.info("pipeline_worker_complete", job_id=job_id)
            return f"Job {job_id} completed successfully"
        finally:
            if hasattr(llm, "aclose"):
                await llm.aclose()
            if vision_llm is not None and hasattr(vision_llm, "aclose"):
                await vision_llm.aclose()

    except Exception as e:
        logger.error("pipeline_worker_failed", job_id=job_id, error=str(e))

        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)[:2000]
                job.updated_at = datetime.now(UTC)
                await session.commit()

        return f"Job {job_id} failed: {e}"


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
