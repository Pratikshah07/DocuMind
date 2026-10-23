import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.document import Document
from app.models.enums import DocumentStatus, JobStatus, db_enum


class ProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per processing attempt, so the lifecycle and timings are observable.

    Created by the pipeline in Phase 3; the table exists from migration 0001.
    """

    __tablename__ = "processing_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        db_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.QUEUED
    )
    stage: Mapped[DocumentStatus | None] = mapped_column(db_enum(DocumentStatus, "job_stage"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="jobs")
