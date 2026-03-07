"""Job database model — tracks coursework generation jobs."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        index=True,
    )

    # Job parameters
    work_type: Mapped[str] = mapped_column(String(20), default="coursework")
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    university: Mapped[str] = mapped_column(String(200), default="")
    discipline: Mapped[str] = mapped_column(String(200), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=30)
    language: Mapped[str] = mapped_column(String(5), default="ru")
    template_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    additional_instructions: Mapped[str] = mapped_column(Text, default="")

    # Status tracking
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    stage_message: Mapped[str] = mapped_column(Text, default="")

    # Pipeline data (stored as JSON for flexibility)
    pipeline_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    research_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outline_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fact_check_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Reference template for visual matching
    reference_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Output
    document_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Cost tracking
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="jobs")

    def __repr__(self) -> str:
        return f"<Job id={self.id} status={self.status} topic={self.topic[:50]}>"
