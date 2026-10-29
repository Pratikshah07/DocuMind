"""User corrections: audit trail and re-application after reprocessing.

Every accepted PATCH change is stored in ``extraction_edits`` (old and new value). That
table is the source of truth for what the user corrected, independent of the current
extraction rows, so corrections survive a reprocess, and even a reprocess that fails.

Policy (supersedes D35):
- Reprocessing re-extracts from the file, then re-applies the *active* corrections:
  the latest edit per field made after the most recent reset.
- "Discard my corrections" (``POST /process?discard_corrections=true``) records a reset,
  so the next run shows the document exactly as extracted. The edits stay in the history.
- A correction that no longer parses (e.g. the date order setting changed) is skipped and
  logged, never guessed.
"""

import json
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentType, ExtractionEdit
from app.services.extraction.parsers import DateOrder, parse_amount, parse_date
from app.services.extraction.types import (
    FIELD_KINDS,
    METHOD_USER,
    FieldKind,
    FieldResult,
    LineItemResult,
)

if TYPE_CHECKING:
    from app.services.extraction_service import ExtractionOutcome

logger = logging.getLogger(__name__)

KIND_EDIT = "edit"
KIND_RESET = "reset"
DOCUMENT_TYPE = "document_type"
LINE_ITEMS = "line_items"
MAX_TEXT = {"vendor_name": 255, "invoice_number": 100, "payment_method": 100}


# --- Parsing user input (shared by PATCH and re-application) -------------------


def user_field(name: str, raw: str | None, date_order: DateOrder) -> FieldResult:
    """A user-entered value as a field. Raises ValueError with a user-facing message."""
    kind = FIELD_KINDS[name]
    text = raw.strip() if isinstance(raw, str) else None
    if not text:  # explicit clear: the user says the document has no such value
        return FieldResult(name, method=METHOD_USER, user_edited=True)
    if kind == FieldKind.DATE:
        parsed = parse_date(text, date_order)
        if parsed is None:
            raise ValueError("Not a valid date. Use YYYY-MM-DD.")
        if parsed.ambiguous:
            raise ValueError("Ambiguous date. Use YYYY-MM-DD.")
        normalized: Any = parsed.value
    elif kind == FieldKind.AMOUNT:
        amount = parse_amount(text)
        if amount is None or amount.ambiguous:
            raise ValueError(
                "Not a valid amount. Use digits with an optional '.' decimal point, e.g. 1249.50."
            )
        normalized = amount.value
    elif kind == FieldKind.CURRENCY:
        if not re.fullmatch(r"[A-Za-z]{3}", text):
            raise ValueError("Use a 3-letter ISO currency code, e.g. USD.")
        normalized = text = text.upper()
    else:
        limit = MAX_TEXT.get(name, 300)
        if len(text) > limit:
            raise ValueError(f"Too long (max {limit} characters).")
        normalized = text
    return FieldResult(name, text, normalized, 1.0, METHOD_USER, user_edited=True)


def _num(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def line_items_to_json(items: list[LineItemResult]) -> str:
    return json.dumps(
        [
            {
                "description": i.description,
                "quantity": _num(i.quantity),
                "unit_price": _num(i.unit_price),
                "total": _num(i.total),
            }
            for i in items
        ]
    )


def line_items_from_json(raw: str) -> list[LineItemResult]:
    def dec(value: Any) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    return [
        LineItemResult(
            row.get("description"),
            dec(row.get("quantity")),
            dec(row.get("unit_price")),
            dec(row.get("total")),
            1.0,
            None,
        )
        for row in json.loads(raw)
    ]


# --- Audit trail -------------------------------------------------------------------


def record_edit(db: Session, document_id: uuid.UUID, field: str, old: str | None, new: str | None) -> None:
    db.add(ExtractionEdit(document_id=document_id, kind=KIND_EDIT, field=field, old_value=old, new_value=new))


def record_reset(db: Session, document_id: uuid.UUID) -> None:
    db.add(ExtractionEdit(document_id=document_id, kind=KIND_RESET))


def history(db: Session, document_id: uuid.UUID) -> list[ExtractionEdit]:
    return list(
        db.scalars(
            select(ExtractionEdit)
            .where(ExtractionEdit.document_id == document_id)
            .order_by(ExtractionEdit.created_at, ExtractionEdit.id)
        ).all()
    )


def active_corrections(db: Session, document_id: uuid.UUID) -> dict[str, str | None]:
    """Latest value per field, counting only edits after the most recent reset."""
    active: dict[str, str | None] = {}
    for edit in history(db, document_id):
        if edit.kind == KIND_RESET:
            active.clear()
        elif edit.field:
            active[edit.field] = edit.new_value
    return active


def apply_corrections(
    outcome: "ExtractionOutcome", corrections: dict[str, str | None], date_order: DateOrder
) -> list[str]:
    """Overlay corrections on a fresh extraction (before validation). Returns the fields applied."""
    applied = []
    for name, value in corrections.items():
        try:
            if name == DOCUMENT_TYPE:
                if value is None:
                    continue
                outcome.document_type = DocumentType(value)
                outcome.type_confidence = 1.0
                outcome.type_user_edited = True
            elif name == LINE_ITEMS:
                outcome.line_items = line_items_from_json(value or "[]")
            elif name in FIELD_KINDS:
                outcome.fields[name] = user_field(name, value, date_order)
            else:
                continue
        except (ValueError, InvalidOperation, json.JSONDecodeError, TypeError):
            # Field names only, never values.
            logger.warning("correction_not_reapplied", extra={"field": name})
            continue
        applied.append(name)
    return applied
