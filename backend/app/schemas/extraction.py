import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from app.models import Document, DocumentStatus, DocumentType, WarningSeverity
from app.services import confidence
from app.services.extraction.types import FIELD_KINDS, FIELD_NAMES, REQUIRED_FIELDS, FieldKind
from app.services.extraction_service import ExtractionOutcome, ExtractionUpdate, LineItemInput
from app.services.validation_service import ValidationConfig, field_status

Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
FieldStatus = Literal["ok", "uncertain", "invalid", "missing"]
Level = Literal["high", "medium", "low"]


class ExtractedFieldView(BaseModel):
    name: str
    status: FieldStatus = Field(
        description="`ok` · `uncertain` (low confidence or a warning) · `invalid` (found but not a valid "
        "value; see `value`) · `missing` (not in the document)."
    )
    value: str | None = Field(description="Exactly as found in the document (or as entered by the user).")
    normalized_value: Any | None = Field(
        description="Typed value: ISO date string, number for amounts, ISO currency code. Null if invalid."
    )
    confidence: float | None = Field(description="Extraction-time heuristic score (0–1), not a probability.")
    effective_confidence: float | None = Field(
        description="`confidence` lowered by failed consistency checks."
    )
    confidence_level: Level | None
    method: str | None = Field(
        description="`regex` (labelled value) · `pattern` (layout heuristic) · `user`."
    )
    page_number: int | None
    required: bool
    is_user_edited: bool


class LineItemView(BaseModel):
    position: int
    description: str | None
    quantity: Amount | None
    unit_price: Amount | None
    total: Amount | None
    confidence: float | None
    page_number: int | None


class WarningView(BaseModel):
    field: str | None
    code: str
    message: str
    severity: WarningSeverity


class ExtractionEditView(BaseModel):
    model_config = {"from_attributes": True}

    kind: Literal["edit", "reset"] = Field(
        description="`edit`: a correction. `reset`: corrections discarded when reprocessing."
    )
    field: str | None = Field(description="Field name, `document_type` or `line_items` (JSON values).")
    old_value: str | None
    new_value: str | None = Field(description="Null means the value was cleared.")
    created_at: datetime


class ExtractionHistoryResponse(BaseModel):
    document_id: uuid.UUID
    edits: list[ExtractionEditView]


class DocumentExtractionResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    document_type: DocumentType
    document_type_confidence: float | None
    document_type_user_edited: bool
    overall_confidence: float = Field(
        description="Mean effective confidence of the required fields (missing/invalid count as 0)."
    )
    needs_review: bool
    line_items_user_edited: bool = Field(description="The line items are the user's correction.")
    fields: list[ExtractedFieldView]
    line_items: list[LineItemView]
    warnings: list[WarningView]


def _json_value(kind: FieldKind, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_response(
    document: Document, outcome: ExtractionOutcome, config: ValidationConfig
) -> DocumentExtractionResponse:
    required = set(REQUIRED_FIELDS[outcome.document_type])
    fields = []
    for name in FIELD_NAMES:
        f = outcome.fields[name]
        effective = outcome.effective.get(name)
        fields.append(
            ExtractedFieldView(
                name=name,
                status=field_status(f, effective, outcome.issues, config),  # type: ignore[arg-type]
                value=f.value,
                normalized_value=_json_value(FIELD_KINDS[name], f.normalized),
                confidence=None if f.is_missing else f.confidence,
                effective_confidence=effective,
                confidence_level=confidence.level(  # type: ignore[arg-type]
                    effective, high=config.confidence_high, medium=config.confidence_review
                ),
                method=f.method,
                page_number=f.page_number,
                required=name in required,
                is_user_edited=f.user_edited,
            )
        )
    return DocumentExtractionResponse(
        document_id=document.id,
        status=document.status,
        document_type=outcome.document_type,
        document_type_confidence=outcome.type_confidence,
        document_type_user_edited=outcome.type_user_edited,
        overall_confidence=outcome.overall_confidence,
        needs_review=outcome.needs_review,
        line_items_user_edited=outcome.line_items_user_edited,
        fields=fields,
        line_items=[
            LineItemView(
                position=i,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total=item.total,
                confidence=item.confidence,
                page_number=item.page_number,
            )
            for i, item in enumerate(outcome.line_items, start=1)
        ],
        warnings=[
            WarningView(field=w.field, code=w.code, message=w.message, severity=w.severity)
            for w in outcome.issues
        ],
    )


# --- PATCH body ----------------------------------------------------------------

_Num = Annotated[Decimal | None, Field(default=None, ge=0, le=Decimal("999999999999.99"))]


class LineItemUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    quantity: _Num = None
    unit_price: _Num = None
    total: _Num = None


class ExtractionUpdateRequest(BaseModel):
    fields: dict[str, str | None] = Field(
        default_factory=dict,
        description=(
            "Corrections by field name. Dates as YYYY-MM-DD (unambiguous formats also accepted), "
            'amounts as numbers in a string (e.g. "1249.50"), currency as an ISO code. '
            '`null` or "" records that the document has no such value.'
        ),
        examples=[{"invoice_number": "INV-2041", "invoice_date": "2025-03-18", "total": "54.00"}],
    )
    document_type: DocumentType | None = Field(default=None, description="Override the classification.")
    line_items: list[LineItemUpdate] | None = Field(
        default=None, max_length=500, description="If given, replaces all line items."
    )

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        unknown = sorted(set(value) - set(FIELD_NAMES))
        if unknown:
            raise ValueError(f"Unknown field(s): {', '.join(unknown)}. Allowed: {', '.join(FIELD_NAMES)}.")
        return value

    def to_update(self) -> ExtractionUpdate:
        return ExtractionUpdate(
            fields=dict(self.fields),
            document_type=self.document_type,
            line_items=None
            if self.line_items is None
            else [LineItemInput(i.description, i.quantity, i.unit_price, i.total) for i in self.line_items],
        )
