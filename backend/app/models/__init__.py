"""ORM models.

Import every model module here so ``Base.metadata`` is complete for Alembic
autogenerate and for test fixtures that call ``create_all``.
"""

from app.db.base import Base
from app.models.document import (
    Document,
    DocumentPage,
    ExtractedField,
    ExtractionEdit,
    LineItem,
    ValidationWarning,
)
from app.models.enums import DocumentStatus, DocumentType, JobStatus, TextSource, WarningSeverity
from app.models.processing_job import ProcessingJob
from app.models.stored_file import StoredFile
from app.models.user import User

__all__ = [
    "Base",
    "Document",
    "DocumentPage",
    "DocumentStatus",
    "DocumentType",
    "ExtractedField",
    "ExtractionEdit",
    "JobStatus",
    "LineItem",
    "ProcessingJob",
    "StoredFile",
    "TextSource",
    "User",
    "ValidationWarning",
    "WarningSeverity",
]
