"""Job-related schemas shared between backend and bot."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkType(StrEnum):
    COURSEWORK = "coursework"
    ARTICLE = "article"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    OUTLINING = "outlining"
    WRITING = "writing"
    FACT_CHECKING = "fact_checking"
    FORMATTING = "formatting"
    FINALIZING = "finalizing"


class JobCreate(BaseModel):
    """Request to create a new coursework generation job."""

    work_type: WorkType = Field(
        default=WorkType.COURSEWORK,
        description="Type of work: coursework or article",
    )
    topic: str = Field(..., min_length=5, max_length=500, description="Work topic")
    university: str = Field(
        default="",
        max_length=200,
        description="University name for format selection",
    )
    discipline: str = Field(
        default="",
        max_length=200,
        description="Academic discipline",
    )
    page_count: int = Field(
        default=30,
        ge=5,
        le=80,
        description="Target page count (5-15 for articles, 15-80 for coursework)",
    )
    language: str = Field(default="ru", description="Output language (ru or en)")
    template_id: str | None = Field(
        default=None,
        description="ГОСТ template ID to use. Defaults to ГОСТ 7.32-2017.",
    )
    additional_instructions: str = Field(
        default="",
        max_length=2000,
        description="Any extra instructions for the generation pipeline",
    )


class JobProgress(BaseModel):
    """Current progress of a generation job."""

    stage: JobStage
    progress_pct: int = Field(ge=0, le=100)
    message: str = ""
    sources_found: int = 0
    sections_written: int = 0
    sections_total: int = 0
    claims_checked: int = 0


class JobResponse(BaseModel):
    """Full job response returned from API."""

    id: str
    status: JobStatus
    work_type: WorkType = WorkType.COURSEWORK
    topic: str
    university: str
    discipline: str
    page_count: int
    language: str
    template_id: str | None
    progress: JobProgress | None = None
    document_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
