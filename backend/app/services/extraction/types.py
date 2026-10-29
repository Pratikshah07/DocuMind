"""Data passed between the extraction layers. Plain dataclasses: no ORM, no I/O."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.models import DocumentType, TextSource


class FieldKind(StrEnum):
    TEXT = "text"
    DATE = "date"
    AMOUNT = "amount"
    CURRENCY = "currency"


# The structured-extraction schema (IMPLEMENTATION_PLAN §14). Order = display order.
FIELD_KINDS: dict[str, FieldKind] = {
    "vendor_name": FieldKind.TEXT,
    "invoice_number": FieldKind.TEXT,
    "invoice_date": FieldKind.DATE,
    "due_date": FieldKind.DATE,
    "currency": FieldKind.CURRENCY,
    "subtotal": FieldKind.AMOUNT,
    "tax": FieldKind.AMOUNT,
    "discount": FieldKind.AMOUNT,
    "total": FieldKind.AMOUNT,
    "payment_method": FieldKind.TEXT,
    "buyer_name": FieldKind.TEXT,
    "po_number": FieldKind.TEXT,
    "vendor_tax_id": FieldKind.TEXT,
    "billing_address": FieldKind.TEXT,
    "shipping_address": FieldKind.TEXT,
}
FIELD_NAMES = tuple(FIELD_KINDS)

# A missing/invalid/low-confidence required field sends the document to review.
REQUIRED_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.INVOICE: ("vendor_name", "invoice_number", "invoice_date", "total"),
    DocumentType.RECEIPT: ("vendor_name", "invoice_date", "total"),
    DocumentType.UNKNOWN: ("vendor_name", "invoice_date", "total"),
}

# How a value was obtained. Stored in extracted_fields.method.
METHOD_LABEL = "regex"  # value next to a recognised label ("Invoice No: 123")
METHOD_PATTERN = "pattern"  # positional/format heuristic (first prominent line = vendor)
METHOD_RULE = "rule"  # rule-based classification
METHOD_USER = "user"  # corrected by a person

# Per-field flags raised during extraction; each becomes a validation warning.
FLAG_AMBIGUOUS_DATE = "ambiguous_date"
FLAG_AMBIGUOUS_AMOUNT = "ambiguous_amount"
FLAG_MULTIPLE_CANDIDATES = "multiple_candidates"
FLAG_INVALID_FORMAT = "invalid_format"
FIELD_FLAGS = (FLAG_AMBIGUOUS_DATE, FLAG_AMBIGUOUS_AMOUNT, FLAG_MULTIPLE_CANDIDATES, FLAG_INVALID_FORMAT)

Normalized = str | date | Decimal | None


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    text_source: TextSource | None = None
    ocr_confidence: float | None = None


@dataclass
class FieldResult:
    """One extracted field. ``value`` is exactly what the document says; ``normalized`` its typed form.

    value None                → missing
    value set, normalized None → invalid (found, but not a valid date/amount/...)
    """

    name: str
    value: str | None = None
    normalized: Normalized = None
    confidence: float | None = None
    method: str | None = None
    page_number: int | None = None
    flags: set[str] = field(default_factory=set)
    # Free-form details for warning messages (e.g. the alternative date reading).
    notes: dict[str, str] = field(default_factory=dict)
    user_edited: bool = False
    # Where the value is on its page: [x0, y0, x1, y1] as fractions of the page size. Set only when
    # the value's words were found exactly once on that page (see extraction/layout.py).
    bbox: list[float] | None = None

    @property
    def is_missing(self) -> bool:
        return self.value is None

    @property
    def is_invalid(self) -> bool:
        return self.value is not None and self.normalized is None


@dataclass
class LineItemResult:
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    total: Decimal | None
    confidence: float
    page_number: int | None
    raw: str = ""  # the source line, kept for debugging in tests (never logged)


@dataclass
class Classification:
    document_type: DocumentType
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    classification: Classification
    fields: dict[str, FieldResult]
    line_items: list[LineItemResult] = field(default_factory=list)
