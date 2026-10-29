"""Automatic deletion of old documents (RETENTION_HOURS) for the public demo.

Runs periodically from the app lifespan. Rows go first (cascading to pages, fields,
line items, warnings and jobs), then the stored files: the same order as a manual
delete, so a failure can leave an orphaned file but never a row without its file.
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.base import utcnow
from app.models import Document
from app.services.storage import StorageBackend

logger = logging.getLogger(__name__)


def purge_expired(
    session_factory: Callable[[], Session], storage: StorageBackend, retention_hours: int
) -> int:
    if retention_hours <= 0:
        return 0
    cutoff = utcnow() - timedelta(hours=retention_hours)
    deleted = 0
    with session_factory() as db:
        documents = db.scalars(
            select(Document).where(Document.created_at < cutoff).options(selectinload(Document.pages))
        ).all()
        for document in documents:
            keys = [document.storage_key] + [p.preview_key for p in document.pages if p.preview_key]
            db.delete(document)
            db.commit()
            for key in keys:
                try:
                    storage.delete(key)
                except Exception:
                    logger.exception("retention_file_delete_failed", extra={"document_id": str(document.id)})
            deleted += 1
    if deleted:
        logger.info("retention_purged", extra={"documents": deleted, "retention_hours": retention_hours})
    return deleted
