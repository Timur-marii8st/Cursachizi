"""Job management API routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db
from backend.app.models.job import Job
from backend.app.models.user import User
from shared.schemas.job import (
    JobCreate,
    JobProgress,
    JobResponse,
    JobStage,
    JobStatus,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    # TODO: Add auth dependency to get current user
) -> JobResponse:
    """Create a new coursework generation job."""
    # For MVP, create/get a default user
    default_user = await _get_or_create_default_user(db)

    job = Job(
        user_id=default_user.id,
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
    await db.refresh(job)

    # TODO: Enqueue the job to arq worker
    # await arq_pool.enqueue_job("run_pipeline", job.id)

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
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[JobResponse]:
    """List all jobs (for current user)."""
    query = (
        select(Job)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [_job_to_response(j) for j in jobs]


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Cancel a pending or running job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in status: {job.status}",
        )
    job.status = JobStatus.CANCELLED
    job.updated_at = datetime.utcnow()
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
