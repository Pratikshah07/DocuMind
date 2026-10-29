"""Document and its extraction results.

``documents`` carries denormalized headline fields (vendor, dates, totals) so
listing and analytics don't need joins. The per-field provenance (method,
confidence, page, bounding box) lives in ``extracted_fields``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentStatus, DocumentType, TextSource, WarningSeverity, db_enum

if TYPE_CHECKING:
    from app.models.processing_job import ProcessingJob

Money = Numeric(14, 2)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    # Default list sort is newest-first.
    __table_args__ = (Index("ix_documents_created_at", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Anonymous demo workspace: SHA-256 of the browser's X-Workspace-Token ("local" in development).
    # Every query is scoped by it, so visitors never see each other's documents.
    workspace_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="local", server_default="local", index=True
    )

    # --- File ---
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)

    # --- Processing ---
    status: Mapped[DocumentStatus] = mapped_column(
        db_enum(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        index=True,
    )
    # NULL until classified (Phase 4); UNKNOWN means "classified, but not an invoice/receipt".
    document_type: Mapped[DocumentType | None] = mapped_column(
        db_enum(DocumentType, "document_type"), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Headline extracted fields ---
    vendor_name: Mapped[str | None] = mapped_column(String(255), index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[date | None] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[Decimal | None] = mapped_column(Money)
    discount: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal | None] = mapped_column(Money)
    payment_method: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    overall_confidence: Mapped[float | None] = mapped_column(Float)

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentPage.page_number",
    )
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExtractedField.name",
    )
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LineItem.position",
    )
    warnings: Mapped[list["ValidationWarning"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


def _document_fk(*, index: bool = True) -> Mapped[uuid.UUID]:
    # index=False where a unique constraint already leads with document_id.
    return mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=index)


class DocumentPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    document_id: Mapped[uuid.UUID] = _document_fk(index=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    text: Mapped[str | None] = mapped_column(Text)
    text_source: Mapped[TextSource | None] = mapped_column(db_enum(TextSource, "text_source"))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    preview_key: Mapped[str | None] = mapped_column(String(512))

    document: Mapped[Document] = relationship(back_populates="pages")

    @property
    def has_preview(self) -> bool:
        return self.preview_key is not None


class ExtractedField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    document_id: Mapped[uuid.UUID] = _document_fk(index=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)  # as found in the document
    normalized_value: Mapped[Any | None] = mapped_column(JSONType)  # typed form, e.g. ISO date
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String(32))  # regex / pattern / nlp / llm / user
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[Any | None] = mapped_column(JSONType)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    document: Mapped[Document] = relationship(back_populates="fields")


class LineItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "line_items"

    document_id: Mapped[uuid.UUID] = _document_fk()
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    total: Mapped[Decimal | None] = mapped_column(Money)
    confidence: Mapped[float | None] = mapped_column(Float)
    page_number: Mapped[int | None] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="line_items")


class ValidationWarning(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "validation_warnings"

    document_id: Mapped[uuid.UUID] = _document_fk()
    field: Mapped[str | None] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[WarningSeverity] = mapped_column(
        db_enum(WarningSeverity, "warning_severity"), nullable=False, default=WarningSeverity.WARNING
    )

    document: Mapped[Document] = relationship(back_populates="warnings")
