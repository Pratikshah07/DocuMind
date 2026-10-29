"""Request-side processing control: enqueue (with concurrency guard) and status."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.workspace import LOCAL_WORKSPACE
from app.db.base import utcnow
from app.models import Document, JobStatus, ProcessingJob
from app.services.jobs import JobRunner
from app.services.pipeline import DocumentProcessor

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class ProcessingService:
    def __init__(
        self,
        db: Session,
        runner: JobRunner,
        processor: DocumentProcessor,
        *,
        stale_after_seconds: int,
        workspace_id: str = LOCAL_WORKSPACE,
    ) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.runner = runner
        self.processor = processor
        self.stale_after = timedelta(seconds=stale_after_seconds)

    def enqueue(self, document_id: uuid.UUID) -> ProcessingJob:
        # Row lock (PostgreSQL) so two concurrent requests can't both queue a job.
        document = self.db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.workspace_id == self.workspace_id)
            .with_for_update()
        )
        if document is None:
            raise NotFoundError("Document not found.", code="document_not_found")

        active = self.latest_job(document_id, statuses=ACTIVE_JOB_STATUSES)
        if active is not None:
            if utcnow() - _aware(active.updated_at) < self.stale_after:
                self.db.rollback()
                raise ConflictError("This document is already being processed.", code="already_processing")
            active.status = JobStatus.FAILED
            active.error_code = "stale_job"
            active.error_detail = "No progress within the stale timeout (process restarted?)."
            active.finished_at = utcnow()
            logger.warning(
                "processing_job_stale", extra={"document_id": str(document_id), "job_id": str(active.id)}
            )

        attempts = self.db.scalar(
            select(func.count()).select_from(ProcessingJob).where(ProcessingJob.document_id == document_id)
        )
        job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED, attempt=(attempts or 0) + 1)
        self.db.add(job)
        self.db.commit()

        self.runner.submit(self.processor.run, job.id)
        logger.info("processing_queued", extra={"document_id": str(document_id), "attempt": job.attempt})
        return job

    def status(self, document_id: uuid.UUID) -> tuple[Document, ProcessingJob | None]:
        document = self.db.scalar(
            select(Document).where(Document.id == document_id, Document.workspace_id == self.workspace_id)
        )
        if document is None:
            raise NotFoundError("Document not found.", code="document_not_found")
        return document, self.latest_job(document_id)

    def latest_job(
        self, document_id: uuid.UUID, *, statuses: tuple[JobStatus, ...] | None = None
    ) -> ProcessingJob | None:
        query = select(ProcessingJob).where(ProcessingJob.document_id == document_id)
        if statuses:
            query = query.where(ProcessingJob.status.in_(statuses))
        # attempt is strictly increasing per document; created_at can tie at clock resolution.
        return self.db.scalar(query.order_by(ProcessingJob.attempt.desc()).limit(1))
