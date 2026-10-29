"""Document lifecycle: upload, query, file access, delete.

Consistency rules between the database and file storage:
- Upload writes the file first, then the row. If the row can't be committed,
  the file is removed, so there is never a row pointing at a missing file.
- Delete removes the row first, then the file. A failed file delete leaves an
  orphaned file (logged), never a row without its file.
"""

import logging
import uuid
from collections.abc import Iterator
from typing import BinaryIO

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, NotFoundError
from app.core.workspace import LOCAL_WORKSPACE
from app.models import Document, DocumentPage, DocumentStatus
from app.schemas.document import DocumentFilters, DocumentSort
from app.services.storage import ORIGINALS, StorageBackend
from app.services.upload_validation import validate_upload

logger = logging.getLogger(__name__)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DocumentService:
    def __init__(
        self,
        db: Session,
        storage: StorageBackend,
        *,
        max_upload_size: int,
        workspace_id: str = LOCAL_WORKSPACE,
        max_documents: int = 0,
    ) -> None:
        self.db = db
        self.storage = storage
        self.max_upload_size = max_upload_size
        self.workspace_id = workspace_id  # every query below is scoped to this workspace
        self.max_documents = max_documents

    # --- Commands ---

    def upload(self, *, filename: str | None, content_type: str | None, stream: BinaryIO) -> Document:
        if self.max_documents and self._count() >= self.max_documents:
            raise ConflictError(
                f"This demo workspace holds at most {self.max_documents} documents. "
                "Delete some to upload more.",
                code="workspace_limit_reached",
                details={"max_documents": self.max_documents},
            )
        validated = validate_upload(
            filename=filename,
            declared_mime_type=content_type,
            stream=stream,
            max_size=self.max_upload_size,
        )
        document_id = uuid.uuid4()
        storage_key = f"{ORIGINALS}/{document_id}{validated.kind.extension}"

        with validated.content:
            self.storage.save(storage_key, validated.content)

        document = Document(
            id=document_id,
            original_filename=validated.filename,
            storage_key=storage_key,
            mime_type=validated.mime_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
            status=DocumentStatus.UPLOADED,
            workspace_id=self.workspace_id,
        )
        try:
            self.db.add(document)
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.storage.delete(storage_key)
            logger.exception("document_upload_db_failed", extra={"document_id": str(document_id)})
            raise

        # IDs, sizes and types only: filenames can be sensitive ("medical-bill-jane-doe.pdf").
        logger.info(
            "document_uploaded",
            extra={
                "document_id": str(document_id),
                "mime_type": validated.mime_type,
                "size_bytes": validated.size_bytes,
            },
        )
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        document = self._get(document_id, options=(selectinload(Document.pages),))
        keys = [document.storage_key] + [p.preview_key for p in document.pages if p.preview_key]
        self.db.delete(document)
        self.db.commit()
        for key in keys:
            try:
                self.storage.delete(key)
            except Exception:
                logger.exception("document_file_delete_failed", extra={"document_id": str(document_id)})
        logger.info("document_deleted", extra={"document_id": str(document_id)})

    # --- Queries ---

    def get(self, document_id: uuid.UUID) -> Document:
        return self._get(
            document_id,
            options=(
                selectinload(Document.pages),
                selectinload(Document.fields),
                selectinload(Document.line_items),
                selectinload(Document.warnings),
            ),
        )

    def delete_all(self) -> int:
        """Delete every document in this workspace (the "clear my demo data" action)."""
        ids = self.db.scalars(select(Document.id).where(Document.workspace_id == self.workspace_id)).all()
        for document_id in ids:
            self.delete(document_id)
        return len(ids)

    def list(self, filters: DocumentFilters) -> tuple[list[Document], int]:
        query = self._filtered(select(Document), filters)
        total = self.db.scalar(self._filtered(select(func.count()).select_from(Document), filters)) or 0
        rows = self.db.scalars(
            self._sorted(query, filters.sort).limit(filters.limit).offset(filters.offset)
        ).all()
        return list(rows), total

    def open_file(self, document_id: uuid.UUID) -> tuple[Document, Iterator[bytes]]:
        document = self._get(document_id)
        if not self.storage.exists(document.storage_key):
            logger.error("document_file_missing", extra={"document_id": str(document_id)})
            raise NotFoundError("The original file for this document is missing.", code="file_not_found")
        return document, self.storage.iter_chunks(document.storage_key)

    def open_preview(self, document_id: uuid.UUID, page_number: int) -> Iterator[bytes]:
        self._get(document_id)
        page = self.db.scalar(
            select(DocumentPage).where(
                DocumentPage.document_id == document_id, DocumentPage.page_number == page_number
            )
        )
        if page is None or page.preview_key is None or not self.storage.exists(page.preview_key):
            raise NotFoundError("No preview is available for this page.", code="preview_not_found")
        return self.storage.iter_chunks(page.preview_key)

    # --- Helpers ---

    def _get(self, document_id: uuid.UUID, options: tuple = ()) -> Document:
        document = self.db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.workspace_id == self.workspace_id)
            .options(*options)
        )
        if document is None:
            raise NotFoundError("Document not found.", code="document_not_found")
        return document

    def _count(self) -> int:
        return (
            self.db.scalar(
                select(func.count()).select_from(Document).where(Document.workspace_id == self.workspace_id)
            )
            or 0
        )

    def _filtered(self, query: Select, filters: DocumentFilters) -> Select:
        query = query.where(Document.workspace_id == self.workspace_id)
        if filters.q and (term := filters.q.strip()):
            pattern = f"%{_escape_like(term)}%"
            query = query.where(
                or_(
                    Document.original_filename.ilike(pattern, escape="\\"),
                    Document.vendor_name.ilike(pattern, escape="\\"),
                )
            )
        if filters.status:
            query = query.where(Document.status.in_(filters.status))
        if filters.document_type:
            query = query.where(Document.document_type == filters.document_type)
        if filters.date_from:
            query = query.where(Document.invoice_date >= filters.date_from)
        if filters.date_to:
            query = query.where(Document.invoice_date <= filters.date_to)
        return query

    @staticmethod
    def _sorted(query: Select, sort: DocumentSort) -> Select:
        # Document.id is the final tie-breaker so pagination is stable.
        order = {
            DocumentSort.NEWEST: (Document.created_at.desc(),),
            DocumentSort.OLDEST: (Document.created_at.asc(),),
            DocumentSort.AMOUNT_DESC: (Document.total.desc().nulls_last(), Document.created_at.desc()),
            DocumentSort.AMOUNT_ASC: (Document.total.asc().nulls_last(), Document.created_at.desc()),
            DocumentSort.VENDOR: (Document.vendor_name.asc().nulls_last(), Document.created_at.desc()),
        }[sort]
        return query.order_by(*order, Document.id)
