"""Periodic housekeeping, run from the app lifespan (single instance, see D47).

- ``recover_interrupted_jobs``: processing runs inside the API process, so a restart or
  crash loses the running job. Jobs still QUEUED/RUNNING after the stale timeout (or,
  at startup, every active job: no other process can be running them) are marked
  FAILED with the retryable code ``interrupted``, and their document is set to FAILED
  so the UI offers a retry instead of showing "processing" forever. Corrections are
  kept (they live in ``extraction_edits``) and re-applied by the retry.
- ``sweep_orphans``: storage objects that no row references (left behind when a file
  delete failed after its row was deleted, or a run crashed after writing previews),
  older than a grace period so in-flight uploads and runs are never touched; plus
  abandoned partial writes.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Document, DocumentPage, DocumentStatus, JobStatus, ProcessingJob
from app.services.analytics_service import IN_PROGRESS
from app.services.extraction_service import clear_extraction
from app.services.storage import StorageBackend

logger = logging.getLogger(__name__)

INTERRUPTED = "interrupted"
INTERRUPTED_MESSAGE = "Processing was interrupted (the server restarted). Retry to process it again."
NOT_QUEUED_MESSAGE = "Processing never started. Retry to process this document."


def _aware(value: datetime) -> datetime:  # SQLite returns naive datetimes; we store UTC
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def recover_interrupted_jobs(
    session_factory: Callable[[], Session], storage: StorageBackend, *, older_than: timedelta | None
) -> int:
    """Fail dead jobs. ``older_than=None`` (startup) treats every active job as dead."""
    cutoff = utcnow() - older_than if older_than is not None else None
    recovered = 0
    preview_keys: list[str] = []
    with session_factory() as db:
        jobs = db.scalars(
            select(ProcessingJob).where(ProcessingJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
        ).all()
        for job in jobs:
            if cutoff is not None and _aware(job.updated_at) >= cutoff:
                continue
            now = utcnow()
            job.status = JobStatus.FAILED
            job.error_code = INTERRUPTED
            job.error_detail = "No progress before restart or stale timeout."
            job.finished_at = now
            document = db.get(Document, job.document_id)
            if document is not None and document.status in IN_PROGRESS:
                preview_keys += _fail_document(db, document, INTERRUPTED_MESSAGE)
            recovered += 1

        # Uploaded, but no job was ever created (the enqueue after the upload commit failed).
        orphans = db.scalars(
            select(Document).where(
                Document.status == DocumentStatus.UPLOADED,
                ~select(ProcessingJob.id).where(ProcessingJob.document_id == Document.id).exists(),
            )
        ).all()
        for document in orphans:
            if cutoff is not None and _aware(document.created_at) >= cutoff:
                continue
            preview_keys += _fail_document(db, document, NOT_QUEUED_MESSAGE)
            recovered += 1
        db.commit()

    for key in preview_keys:
        try:
            storage.delete(key)
        except Exception:
            logger.exception("recovery_preview_delete_failed")
    if recovered:
        logger.warning("processing_jobs_recovered", extra={"count": recovered})
    return recovered


def _fail_document(db: Session, document: Document, message: str) -> list[str]:
    # Same end state as a failed run (pipeline._fail): no stale pages or extraction rows.
    pages = db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).all()
    keys = [p.preview_key for p in pages if p.preview_key]
    for page in pages:
        db.delete(page)
    clear_extraction(db, document)
    document.status = DocumentStatus.FAILED
    document.error_message = message
    document.page_count = None
    document.processed_at = utcnow()
    return keys


def sweep_orphans(
    session_factory: Callable[[], Session], storage: StorageBackend, *, grace: timedelta
) -> int:
    cutoff = utcnow() - grace
    with session_factory() as db:
        referenced = set(db.scalars(select(Document.storage_key)).all())
        referenced |= {k for k in db.scalars(select(DocumentPage.preview_key)).all() if k}
    removed = 0
    for key, modified in list(storage.list_objects()):
        if key in referenced or modified >= cutoff:
            continue
        try:
            if storage.delete(key):
                removed += 1
        except Exception:
            logger.exception("orphan_delete_failed")
    removed += storage.cleanup_temporary(cutoff)
    if removed:
        logger.info("storage_orphans_removed", extra={"count": removed})
    return removed
