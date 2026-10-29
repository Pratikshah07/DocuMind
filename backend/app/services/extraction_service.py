"""Extraction orchestration and persistence.

- ``ExtractionEngine``: pure (no DB). classify → extract fields and line items → validate.
  Used by the processing pipeline.
- ``write_outcome`` / ``clear_extraction``: replace a document's extraction rows in the
  caller's transaction. Delete-then-insert keyed by document, so re-running is
  idempotent: no duplicate fields, line items or warnings.
- ``ExtractionService``: request side. Read the stored extraction; apply user
  corrections and re-validate (PATCH).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.workspace import LOCAL_WORKSPACE
from app.models import (
    Document,
    DocumentStatus,
    DocumentType,
    ExtractedField,
    LineItem,
    ValidationWarning,
)
from app.services import corrections
from app.services import validation_service as validation
from app.services.classification_service import DocumentClassifier, RuleBasedClassifier
from app.services.extraction.parsers import DateOrder
from app.services.extraction.rules import FieldExtractor, RuleBasedExtractor
from app.services.extraction.types import (
    FIELD_KINDS,
    FIELD_NAMES,
    METHOD_RULE,
    METHOD_USER,
    FieldKind,
    FieldResult,
    LineItemResult,
    PageText,
)
from app.services.validation_service import Issue, ValidationConfig

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_FIELD = "document_type"
EDITABLE_STATUSES = (DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW)
_MAX_TEXT = corrections.MAX_TEXT


@dataclass
class ExtractionOutcome:
    document_type: DocumentType
    type_confidence: float | None
    type_user_edited: bool
    fields: dict[str, FieldResult]
    line_items: list[LineItemResult]
    issues: list[Issue]
    effective: dict[str, float | None] = field(default_factory=dict)
    overall_confidence: float = 0.0
    needs_review: bool = True
    line_items_user_edited: bool = False

    @property
    def status(self) -> DocumentStatus:
        return DocumentStatus.NEEDS_REVIEW if self.needs_review else DocumentStatus.COMPLETED


def finalize(outcome: ExtractionOutcome, config: ValidationConfig) -> ExtractionOutcome:
    """Fill the derived parts (effective confidence, overall score, review decision)."""
    outcome.effective = validation.effective_confidences(outcome.fields, outcome.issues)
    outcome.overall_confidence = validation.overall_confidence(
        outcome.document_type, outcome.effective, outcome.fields
    )
    outcome.needs_review = validation.needs_review(
        outcome.document_type, outcome.fields, outcome.effective, outcome.issues, config
    )
    return outcome


@dataclass(frozen=True)
class ExtractionConfig:
    date_order: DateOrder = DateOrder.DMY
    validation: ValidationConfig = field(default_factory=ValidationConfig)


def validation_config(settings: Settings) -> ValidationConfig:
    return ValidationConfig(
        amount_tolerance=Decimal(str(settings.amount_tolerance)),
        confidence_high=settings.confidence_high,
        confidence_review=settings.confidence_review,
    )


def extraction_config(settings: Settings) -> ExtractionConfig:
    return ExtractionConfig(date_order=DateOrder(settings.date_order), validation=validation_config(settings))


class ExtractionEngine:
    def __init__(
        self,
        config: ExtractionConfig | None = None,
        *,
        classifier: DocumentClassifier | None = None,
        extractor: FieldExtractor | None = None,
    ) -> None:
        self.config = config or ExtractionConfig()
        self.classifier = classifier or RuleBasedClassifier()
        self.extractor = extractor or RuleBasedExtractor(date_order=self.config.date_order)

    def extract(self, pages: Sequence[PageText]) -> ExtractionOutcome:
        classification = self.classifier.classify(pages)
        fields, items = self.extractor.extract(pages, classification.document_type)
        return ExtractionOutcome(
            classification.document_type, classification.confidence, False, fields, items, issues=[]
        )

    def validate(self, outcome: ExtractionOutcome) -> ExtractionOutcome:
        outcome.issues = validation.field_level_issues(outcome.fields) + validation.rule_issues(
            outcome.document_type, outcome.fields, outcome.line_items, self.config.validation
        )
        return finalize(outcome, self.config.validation)


# --- Persistence -------------------------------------------------------------


def _encode(kind: FieldKind | None, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)  # exact; the API turns it into a JSON number
    return value


def _decode(kind: FieldKind | None, value: Any) -> Any:
    if value is None:
        return None
    if kind == FieldKind.DATE:
        return date.fromisoformat(value)
    if kind == FieldKind.AMOUNT:
        return Decimal(value)
    return value


def clear_extraction(db: Session, document: Document) -> None:
    for model in (ExtractedField, LineItem, ValidationWarning):
        db.execute(delete(model).where(model.document_id == document.id))
    document.document_type = None
    document.overall_confidence = None
    for name in (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax",
        "discount",
        "total",
        "payment_method",
    ):
        setattr(document, name, None)


def write_outcome(db: Session, document: Document, outcome: ExtractionOutcome) -> None:
    """Replace all extraction rows for ``document`` and update its headline columns (no commit)."""
    clear_extraction(db, document)
    db.add(
        ExtractedField(
            document_id=document.id,
            name=DOCUMENT_TYPE_FIELD,
            value=outcome.document_type.value,
            normalized_value=outcome.document_type.value,
            confidence=outcome.type_confidence,
            method=METHOD_USER if outcome.type_user_edited else METHOD_RULE,
            is_user_edited=outcome.type_user_edited,
        )
    )
    for name in FIELD_NAMES:
        f = outcome.fields[name]
        db.add(
            ExtractedField(
                document_id=document.id,
                name=name,
                value=f.value,
                normalized_value=_encode(FIELD_KINDS[name], f.normalized),
                confidence=None if f.is_missing else f.confidence,
                method=f.method,
                page_number=f.page_number,
                is_user_edited=f.user_edited,
            )
        )
    for position, item in enumerate(outcome.line_items, start=1):
        db.add(
            LineItem(
                document_id=document.id,
                position=position,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total=item.total,
                confidence=item.confidence,
                page_number=item.page_number,
            )
        )
    for issue in outcome.issues:
        db.add(
            ValidationWarning(
                document_id=document.id,
                field=issue.field,
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
            )
        )

    # Headline columns hold only *valid* values; invalid raw text stays in extracted_fields.
    document.document_type = outcome.document_type
    document.overall_confidence = outcome.overall_confidence
    for name in (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "tax",
        "discount",
        "total",
        "payment_method",
    ):
        value = outcome.fields[name].normalized
        if isinstance(value, str) and name in _MAX_TEXT:
            value = value[: _MAX_TEXT[name]]
        setattr(document, name, value)


def load_outcome(document: Document, config: ValidationConfig) -> ExtractionOutcome:
    """Rebuild the outcome from stored rows (no re-extraction, no re-validation)."""
    rows = {row.name: row for row in document.fields}
    type_row = rows.get(DOCUMENT_TYPE_FIELD)
    fields = {}
    for name in FIELD_NAMES:
        row = rows.get(name)
        fields[name] = (
            FieldResult(
                name=name,
                value=row.value,
                normalized=_decode(FIELD_KINDS[name], row.normalized_value),
                confidence=row.confidence,
                method=row.method,
                page_number=row.page_number,
                user_edited=row.is_user_edited,
            )
            if row
            else FieldResult(name)
        )
    items = [
        LineItemResult(i.description, i.quantity, i.unit_price, i.total, i.confidence or 0.0, i.page_number)
        for i in document.line_items
    ]
    issues = [Issue(w.field, w.code, w.message, w.severity) for w in document.warnings]
    outcome = ExtractionOutcome(
        document_type=document.document_type or DocumentType.UNKNOWN,
        type_confidence=type_row.confidence if type_row else None,
        type_user_edited=bool(type_row and type_row.is_user_edited),
        fields=fields,
        line_items=items,
        issues=issues,
    )
    return finalize(outcome, config)


# --- Request side --------------------------------------------------------------


@dataclass
class LineItemInput:
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    total: Decimal | None


@dataclass
class ExtractionUpdate:
    fields: dict[str, str | None] = field(default_factory=dict)
    document_type: DocumentType | None = None
    line_items: list[LineItemInput] | None = None


class ExtractionService:
    def __init__(self, db: Session, config: ExtractionConfig, *, workspace_id: str = LOCAL_WORKSPACE) -> None:
        self.db = db
        self.config = config
        self.workspace_id = workspace_id

    def get(self, document_id: uuid.UUID) -> tuple[Document, ExtractionOutcome]:
        document = self._load(document_id)
        outcome = load_outcome(document, self.config.validation)
        outcome.line_items_user_edited = corrections.LINE_ITEMS in corrections.active_corrections(
            self.db, document_id
        )
        return document, outcome

    def history(self, document_id: uuid.UUID) -> list:
        document = self.db.scalar(
            select(Document.id).where(Document.id == document_id, Document.workspace_id == self.workspace_id)
        )
        if document is None:
            raise NotFoundError("Document not found.", code="document_not_found")
        return corrections.history(self.db, document_id)

    def update(self, document_id: uuid.UUID, update: ExtractionUpdate) -> tuple[Document, ExtractionOutcome]:
        document = self._load(document_id, for_update=True)
        outcome = load_outcome(document, self.config.validation)
        edited = set()

        errors = []
        changes: list[tuple[str, str | None, str | None]] = []  # (field, old, new) for the audit trail
        for name, raw in update.fields.items():
            if name not in FIELD_KINDS:
                errors.append({"field": name, "message": "Unknown field."})
                continue
            try:
                new = corrections.user_field(name, raw, self.config.date_order)
            except ValueError as exc:
                errors.append({"field": name, "message": str(exc)})
                continue
            changes.append((name, outcome.fields[name].value, new.value))
            outcome.fields[name] = new
            edited.add(name)
        if errors:
            self.db.rollback()
            raise ValidationFailedError("Some values could not be accepted.", details=errors)

        if update.document_type is not None:
            changes.append(
                (corrections.DOCUMENT_TYPE, outcome.document_type.value, update.document_type.value)
            )
            outcome.document_type = update.document_type
            outcome.type_confidence = 1.0
            outcome.type_user_edited = True
        if update.line_items is not None:
            new_items = [
                LineItemResult(i.description, i.quantity, i.unit_price, i.total, 1.0, None)
                for i in update.line_items
            ]
            changes.append(
                (
                    corrections.LINE_ITEMS,
                    corrections.line_items_to_json(outcome.line_items),
                    corrections.line_items_to_json(new_items),
                )
            )
            outcome.line_items = new_items

        # Keep how-it-was-read issues for fields nobody touched; recompute every rule-level issue.
        kept = [
            i
            for i in outcome.issues
            if i.code in validation.FIELD_LEVEL_CODES_WITH_INFO and i.field not in edited
        ]
        outcome.issues = kept + validation.rule_issues(
            outcome.document_type, outcome.fields, outcome.line_items, self.config.validation
        )
        finalize(outcome, self.config.validation)

        write_outcome(self.db, document, outcome)
        # Every submitted value is recorded, including confirmations (old == new): a confirmed value
        # is a correction too and must survive reprocessing with its user-confirmed status.
        for name, old, new in changes:
            corrections.record_edit(self.db, document.id, name, old, new)
        document.status = outcome.status
        self.db.commit()
        logger.info(
            "extraction_edited",
            extra={
                "document_id": str(document_id),
                "fields": sorted(edited),  # names only, never values
                "line_items_replaced": update.line_items is not None,
                "status": document.status.value,
            },
        )
        self.db.expire(document)
        return self.get(document_id)

    def _load(self, document_id: uuid.UUID, *, for_update: bool = False) -> Document:
        query = (
            select(Document)
            .where(Document.id == document_id, Document.workspace_id == self.workspace_id)
            .options(
                selectinload(Document.fields),
                selectinload(Document.line_items),
                selectinload(Document.warnings),
            )
        )
        if for_update:
            query = query.with_for_update(of=Document)
        document = self.db.scalar(query)
        if document is None:
            raise NotFoundError("Document not found.", code="document_not_found")
        if document.status not in EDITABLE_STATUSES:
            self.db.rollback()
            raise ConflictError(
                "Extraction results are not available for this document yet.",
                code="extraction_not_ready",
                details={"status": document.status.value},
            )
        return document
