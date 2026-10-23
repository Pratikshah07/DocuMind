import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.enums import DocumentStatus, DocumentType, TextSource, WarningSeverity

# Money is stored as NUMERIC; JSON clients get a number (not Pydantic's default string).
Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentSummary(_ORMModel):
    """One row in the document list."""

    id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    document_type: DocumentType | None
    vendor_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str | None
    total: Amount | None
    category: str | None
    overall_confidence: float | None = Field(description="0–1 heuristic score, not a probability.")
    created_at: datetime
    updated_at: datetime


class DocumentPageOut(_ORMModel):
    page_number: int
    text_source: TextSource | None
    ocr_confidence: float | None
    width: int | None
    height: int | None


class ExtractedFieldOut(_ORMModel):
    name: str
    value: str | None
    normalized_value: Any | None
    confidence: float | None
    method: str | None
    page_number: int | None
    is_user_edited: bool


class LineItemOut(_ORMModel):
    id: uuid.UUID
    position: int
    description: str | None
    quantity: Amount | None
    unit_price: Amount | None
    total: Amount | None
    confidence: float | None
    page_number: int | None


class ValidationWarningOut(_ORMModel):
    field: str | None
    code: str
    message: str
    severity: WarningSeverity


class DocumentDetail(DocumentSummary):
    due_date: date | None
    subtotal: Amount | None
    tax: Amount | None
    discount: Amount | None
    payment_method: str | None
    error_message: str | None = Field(description="User-safe explanation when status is FAILED.")
    processed_at: datetime | None
    pages: list[DocumentPageOut]
    fields: list[ExtractedFieldOut]
    line_items: list[LineItemOut]
    warnings: list[ValidationWarningOut]


class DocumentUploadResponse(_ORMModel):
    id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int = Field(description="Number of documents matching the filters (ignores limit/offset).")
    limit: int
    offset: int


class DocumentSort(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    AMOUNT_DESC = "amount_desc"
    AMOUNT_ASC = "amount_asc"
    VENDOR = "vendor"


class DocumentFilters(BaseModel):
    q: str | None = Field(default=None, max_length=200, description="Matches filename or vendor.")
    status: list[DocumentStatus] | None = None
    document_type: DocumentType | None = None
    date_from: date | None = Field(default=None, description="Invoice date on or after.")
    date_to: date | None = Field(default=None, description="Invoice date on or before.")
    sort: DocumentSort = DocumentSort.NEWEST
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
