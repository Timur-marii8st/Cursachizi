"""Job management API routes."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import uuid4

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import (
    enforce_job_rate_limit,
    get_db,
    verify_internal_api_key,
)
from backend.app.config import get_settings
from backend.app.models.job import Job
from backend.app.models.user import User
from backend.app.services.storage import download_document, upload_document
from backend.app.services.user_service import get_or_create_user_by_telegram_id
from shared.schemas.job import (
    JobCreate,
    JobProgress,
    JobResponse,
    JobStage,
    JobStatus,
    WorkType,
)

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(verify_internal_api_key)],
)


def get_arq_pool(request: Request) -> ArqRedis:
    """Get shared arq Redis pool from app state."""
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Task queue is unavailable",
        )
    return arq_pool


def _job_to_response(job: Job) -> JobResponse:
    """Convert a Job ORM model to a JobResponse schema."""
    progress = None
    if job.status == JobStatus.RUNNING:
        progress = JobProgress(
            stage=JobStage(job.stage),
            progress_pct=job.progress_pct,
            message=job.stage_message,
        )

    return JobResponse(
        id=job.id,
        status=JobStatus(job.status),
        work_type=WorkType(job.work_type),
        topic=job.topic,
        university=job.university,
        discipline=job.discipline,
        page_count=job.page_count,
        language=job.language,
        template_id=job.template_id,
        progress=progress,
        document_url=job.document_url,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    job_in: JobCreate,
    db: AsyncSession = Depends(get_db),
    arq_pool: ArqRedis = Depends(get_arq_pool),
    _rate_limit: None = Depends(enforce_job_rate_limit),
) -> JobResponse:
    """Create a new coursework generation job."""
    # Use real user identified by telegram_id, fall back to default for API testing
    if job_in.telegram_id:
        user = await get_or_create_user_by_telegram_id(db, job_in.telegram_id)
    else:
        user = await _get_or_create_default_user(db)

    settings = get_settings()
    is_admin = job_in.telegram_id and job_in.telegram_id in settings.admin_telegram_id_set

    if is_admin:
        # Admins have unlimited credits — only track total_papers_generated
        await db.execute(
            sql_update(User)
            .where(User.id == user.id)
            .values(total_papers_generated=User.total_papers_generated + 1)
        )
    else:
        # Atomically deduct 1 credit — prevents race conditions
        stmt = (
            sql_update(User)
            .where(User.id == user.id, User.credits_remaining > 0)
            .values(
                credits_remaining=User.credits_remaining - 1,
                total_papers_generated=User.total_papers_generated + 1,
            )
            .returning(User.credits_remaining)
        )
        result = await db.execute(stmt)
        row = result.fetchone()
        if row is None:
            raise HTTPException(
                status_code=402,
                detail="Недостаточно кредитов. Пополните баланс через /buy.",
            )
    await db.refresh(user)

    job = Job(
        user_id=user.id,
        work_type=job_in.work_type,
        topic=job_in.topic,
        university=job_in.university,
        discipline=job_in.discipline,
        page_count=job_in.page_count,
        language=job_in.language,
        template_id=job_in.template_id,
        additional_instructions=job_in.additional_instructions,
        status=JobStatus.PENDING,
        stage=JobStage.QUEUED,
    )
    db.add(job)
    await db.flush()

    # Store user-selected source count in pipeline_config for the worker
    job.pipeline_config = {"max_sources": job_in.source_count}

    await db.refresh(job)

    # Commit before enqueuing to avoid race condition: arq worker must see the
    # committed Job row when it reads from a separate DB connection.
    await db.commit()

    await arq_pool.enqueue_job("run_pipeline", job.id)

    return _job_to_response(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Get job status and details."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    telegram_id: int = Query(...),
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[JobResponse]:
    """List jobs, optionally filtered by telegram_id.

    FIX-004: Without telegram_id filter, all users' jobs were exposed.
    """
    query = select(Job).join(User).where(User.telegram_id == telegram_id).order_by(Job.created_at.desc())
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Cancel a pending or running job.

    FIX-005: Refunds 1 credit when cancelling a PENDING job (work not yet started).
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in status: {job.status}",
        )

    # Refund credit for PENDING jobs — pipeline hasn't consumed LLM tokens yet
    if job.status == JobStatus.PENDING:
        await db.execute(
            sql_update(User)
            .where(User.id == job.user_id)
            .values(credits_remaining=User.credits_remaining + 1)
        )

    job.status = JobStatus.CANCELLED
    job.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(job)
    await db.commit()
    return _job_to_response(job)


@router.get("/{job_id}/download")
async def download_job_document(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the generated .docx document for a completed job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Document not ready yet")
    if not job.document_s3_key:
        raise HTTPException(status_code=404, detail="Document not found in storage")

    settings = get_settings()
    try:
        doc_bytes = await asyncio.to_thread(
            download_document,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket_name,
            object_key=job.document_s3_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to retrieve document from storage") from exc

    safe_topic = job.topic[:50].replace("/", "_").replace("\\", "_")
    filename_utf8 = f"courseforge_{safe_topic}.docx"
    # RFC 5987: filename*=UTF-8'' supports unicode; ascii fallback for old clients
    encoded = quote(filename_utf8, safe=".-_ ")

    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"courseforge.docx\"; filename*=UTF-8''{encoded}"
        },
    )


@router.post("/{job_id}/reference", response_model=JobResponse)
async def upload_reference_template(
    job_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Upload a reference .docx template for visual format matching.

    Must be uploaded before the job starts processing (status=pending).
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload reference for job in status: {job.status}",
        )

    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File must be a .docx document")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    # SEC-005: validate ZIP magic bytes — .docx is a ZIP archive (PK\x03\x04)
    # Extension alone is client-controlled and trivially spoofable.
    if not content.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=400, detail="Invalid .docx file: not a valid ZIP archive")

    # Upload to S3
    settings = get_settings()
    ref_key = f"references/{job_id}/{uuid4()}.docx"

    await asyncio.to_thread(
        upload_document,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket_name,
        object_key=ref_key,
        document_bytes=content,
    )

    job.reference_s3_key = ref_key
    job.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(job)

    return _job_to_response(job)


async def _get_or_create_default_user(db: AsyncSession) -> User:
    """Get or create a default user for MVP (no auth yet)."""
    query = select(User).where(User.username == "default")
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(username="default", first_name="Default", last_name="User")
    db.add(user)
    await db.flush()
    return user


