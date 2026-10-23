"""Enumerations stored in the database.

Stored as VARCHAR with a CHECK constraint (``native_enum=False``) rather than a
PostgreSQL ENUM type: portable to SQLite for tests and simpler to migrate.
"""

from enum import StrEnum

from sqlalchemy import Enum


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    OCR = "OCR"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class DocumentType(StrEnum):
    INVOICE = "INVOICE"
    RECEIPT = "RECEIPT"
    UNKNOWN = "UNKNOWN"


class TextSource(StrEnum):
    EMBEDDED = "EMBEDDED"  # PDF text layer
    OCR = "OCR"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class WarningSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def db_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
