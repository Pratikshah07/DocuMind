"""Layer 6: validation. Records warnings; never changes a value.

Two kinds of issues:
- field-level, raised during extraction (ambiguous date, conflicting candidates,
  unparseable value). They belong to the value as read, so they are kept until
  that field is edited.
- rule-level, recomputed from the current values every time (missing required
  fields, dates out of order, totals that don't add up, line-item arithmetic).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.models import DocumentType, WarningSeverity
from app.services import confidence
from app.services.extraction.types import (
    FIELD_KINDS,
    FLAG_AMBIGUOUS_AMOUNT,
    FLAG_AMBIGUOUS_DATE,
    FLAG_INVALID_FORMAT,
    FLAG_MULTIPLE_CANDIDATES,
    REQUIRED_FIELDS,
    FieldResult,
    LineItemResult,
)

CODE_MISSING_REQUIRED = "missing_required_field"
CODE_TYPE_UNKNOWN = "document_type_unknown"
CODE_TAX_SUMMED = "tax_summed"
CODE_DUE_BEFORE_ISSUE = "due_before_invoice_date"
CODE_DATE_IN_FUTURE = "date_in_future"
CODE_DATE_IMPLAUSIBLE = "date_implausible"
CODE_NEGATIVE_AMOUNT = "negative_amount"
CODE_TOTALS_MISMATCH = "totals_mismatch"
CODE_LINE_ITEMS_MISMATCH = "line_items_mismatch"
CODE_LINE_ITEM_ARITHMETIC = "line_item_arithmetic"
CODE_LOW_CONFIDENCE = "low_confidence"
CODE_DUPLICATE_INVOICE = "duplicate_invoice_number"

# Every rule, with the review action shown next to its warning. Codes are stable API values.
SUGGESTED_ACTIONS = {
    CODE_MISSING_REQUIRED: "Find the value on the document and enter it; leave it empty only if the "
    "document really has none.",
    CODE_TYPE_UNKNOWN: "Check that this is an invoice or receipt, then set the type.",
    CODE_TAX_SUMMED: "Check that these tax lines belong together.",
    CODE_DUE_BEFORE_ISSUE: "Compare both dates with the document; one may be misread.",
    CODE_DATE_IN_FUTURE: "Check the date against the document; it may be misread.",
    CODE_DATE_IMPLAUSIBLE: "Check the date against the document; it may be misread.",
    CODE_NEGATIVE_AMOUNT: "Check whether this is a refund or credit, or a misread sign.",
    CODE_TOTALS_MISMATCH: "Compare subtotal, tax, discount and total with the document and correct the "
    "misread one.",
    CODE_LINE_ITEMS_MISMATCH: "Look for missing, extra or misread line items, or a misread subtotal.",
    CODE_LINE_ITEM_ARITHMETIC: "Check this row's quantity, unit price and line total.",
    CODE_LOW_CONFIDENCE: "Compare the value with the document. Saving it confirms it.",
    CODE_DUPLICATE_INVOICE: "Check whether this invoice was already uploaded before paying or booking it.",
    FLAG_AMBIGUOUS_DATE: "Confirm the date and enter it as YYYY-MM-DD.",
    FLAG_AMBIGUOUS_AMOUNT: "Confirm the amount and enter it with a '.' decimal point.",
    FLAG_MULTIPLE_CANDIDATES: "Check which value the document means and correct it if needed.",
    FLAG_INVALID_FORMAT: "Enter a valid value, or clear the field if the document has none.",
}

# Issues that describe how a value was *read*; they survive re-validation unless the field is edited.
FIELD_LEVEL_CODES = {
    FLAG_AMBIGUOUS_DATE,
    FLAG_AMBIGUOUS_AMOUNT,
    FLAG_MULTIPLE_CANDIDATES,
    FLAG_INVALID_FORMAT,
}
FIELD_LEVEL_CODES_WITH_INFO = FIELD_LEVEL_CODES | {CODE_TAX_SUMMED}
# Cross-field rules lower the effective confidence of every field they involve.
_CONSISTENCY_FIELDS = {
    CODE_TOTALS_MISMATCH: {"subtotal", "tax", "discount", "total"},
    CODE_LINE_ITEMS_MISMATCH: {"subtotal", "total"},
}

_LABELS = {name: name.replace("_", " ") for name in FIELD_KINDS}


@dataclass(frozen=True)
class Issue:
    field: str | None
    code: str
    message: str
    severity: WarningSeverity = WarningSeverity.WARNING


@dataclass(frozen=True)
class ValidationConfig:
    amount_tolerance: Decimal = Decimal("0.02")
    confidence_high: float = 0.85
    confidence_review: float = 0.60  # below this a required field needs review ("medium" threshold)
    max_future_days: int = 31


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def field_level_issues(fields: dict[str, FieldResult]) -> list[Issue]:
    issues: list[Issue] = []
    for name, f in fields.items():
        label = _LABELS.get(name, name)
        if FLAG_INVALID_FORMAT in f.flags:
            kind = FIELD_KINDS.get(name)
            issues.append(
                Issue(
                    name,
                    FLAG_INVALID_FORMAT,
                    f"'{f.value}' was found for {label} but is not a valid "
                    f"{kind.value if kind else 'value'}.",
                    WarningSeverity.ERROR,
                )
            )
        if FLAG_AMBIGUOUS_DATE in f.flags:
            reading = f.normalized.isoformat() if isinstance(f.normalized, date) else f.normalized
            other = f.notes.get("alternative")
            issues.append(
                Issue(
                    name,
                    FLAG_AMBIGUOUS_DATE,
                    f"{label.capitalize()} '{f.value}' is ambiguous: read as {reading}"
                    + (f", but it could also be {other}." if other else "."),
                )
            )
        if FLAG_AMBIGUOUS_AMOUNT in f.flags:
            issues.append(
                Issue(
                    name,
                    FLAG_AMBIGUOUS_AMOUNT,
                    f"{label.capitalize()} '{f.value}' is ambiguous: read as {_money(f.normalized)}"  # type: ignore[arg-type]
                    f", but it could also be {f.notes.get('alternative', 'a decimal value')}.",
                )
            )
        if FLAG_MULTIPLE_CANDIDATES in f.flags:
            issues.append(
                Issue(
                    name,
                    FLAG_MULTIPLE_CANDIDATES,
                    f"Different values were found for {label} ({f.notes.get('candidates', '')}); "
                    f"'{f.value}' was used.",
                )
            )
        if "summed_from" in f.notes:
            issues.append(
                Issue(
                    name,
                    CODE_TAX_SUMMED,
                    f"{label.capitalize()} is the sum of {f.notes['summed_from']}.",
                    WarningSeverity.INFO,
                )
            )
    return issues


def rule_issues(
    document_type: DocumentType,
    fields: dict[str, FieldResult],
    line_items: Sequence[LineItemResult],
    config: ValidationConfig,
    *,
    today: date | None = None,
) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def val(name: str):
        return fields[name].normalized if name in fields else None

    if document_type == DocumentType.UNKNOWN:
        issues.append(
            Issue(
                None, CODE_TYPE_UNKNOWN, "This does not look like an invoice or a receipt; check the values."
            )
        )
    for name in REQUIRED_FIELDS[document_type]:
        if fields[name].is_missing:
            issues.append(Issue(name, CODE_MISSING_REQUIRED, f"No {_LABELS[name]} was found."))

    issued, due = val("invoice_date"), val("due_date")
    if isinstance(issued, date) and isinstance(due, date) and due < issued:
        issues.append(
            Issue("due_date", CODE_DUE_BEFORE_ISSUE, f"Due date {due} is before the invoice date {issued}.")
        )
    for name in ("invoice_date", "due_date"):
        value = val(name)
        if not isinstance(value, date):
            continue
        if name == "invoice_date" and value > today + timedelta(days=config.max_future_days):
            issues.append(Issue(name, CODE_DATE_IN_FUTURE, f"Invoice date {value} is in the future."))
        if value.year < 1990 or value.year > today.year + 10:
            issues.append(
                Issue(name, CODE_DATE_IMPLAUSIBLE, f"{_LABELS[name].capitalize()} {value} looks wrong.")
            )

    for name in ("subtotal", "tax", "total"):
        value = val(name)
        if isinstance(value, Decimal) and value < 0:
            issues.append(
                Issue(
                    name,
                    CODE_NEGATIVE_AMOUNT,
                    f"{_LABELS[name].capitalize()} is negative ({_money(value)}).",
                    WarningSeverity.ERROR,
                )
            )

    subtotal, tax, discount, total = (val(n) for n in ("subtotal", "tax", "discount", "total"))
    amounts = {
        k: v if isinstance(v, Decimal) else None
        for k, v in {"subtotal": subtotal, "tax": tax, "discount": discount, "total": total}.items()
    }
    if amounts["subtotal"] is not None and amounts["total"] is not None:
        expected = amounts["subtotal"] + (amounts["tax"] or 0) - (amounts["discount"] or 0)
        if abs(expected - amounts["total"]) > config.amount_tolerance:
            parts = f"subtotal {_money(amounts['subtotal'])}"
            parts += f" + tax {_money(amounts['tax'])}" if amounts["tax"] is not None else " (no tax found)"
            parts += f" − discount {_money(amounts['discount'])}" if amounts["discount"] is not None else ""
            issues.append(
                Issue(
                    "total",
                    CODE_TOTALS_MISMATCH,
                    f"Totals don't add up: {parts} = {_money(expected)}, "
                    f"but the total is {_money(amounts['total'])}.",
                )
            )

    item_totals = [item.total for item in line_items if item.total is not None]
    if item_totals:
        items_sum = sum(item_totals, Decimal("0"))
        if amounts["subtotal"] is not None:
            target, target_name = amounts["subtotal"], "subtotal"
        elif amounts["total"] is not None:
            target = amounts["total"] - (amounts["tax"] or 0) + (amounts["discount"] or 0)
            target_name = "total before tax and discount"
        else:
            target = None
        tolerance = max(config.amount_tolerance, Decimal("0.005") * len(item_totals))
        if target is not None and abs(items_sum - target) > tolerance:
            issues.append(
                Issue(
                    "subtotal" if target_name == "subtotal" else "total",
                    CODE_LINE_ITEMS_MISMATCH,
                    f"Line items add up to {_money(items_sum)}, but the {target_name} is {_money(target)}.",
                )
            )
    for position, item in enumerate(line_items, start=1):
        if item.quantity is None or item.unit_price is None or item.total is None:
            continue
        computed = item.quantity * item.unit_price
        if abs(computed - item.total) > config.amount_tolerance:
            issues.append(
                Issue(
                    f"line_items[{position}]",
                    CODE_LINE_ITEM_ARITHMETIC,
                    f"Line {position}: {item.quantity.normalize()} × {_money(item.unit_price)} = "
                    f"{_money(computed)}, but the line total is {_money(item.total)}.",
                )
            )
    return issues


# --- Derived views (computed, never stored as truth) -------------------------


def inconsistent_fields(issues: Sequence[Issue]) -> set[str]:
    found: set[str] = set()
    for issue in issues:
        found |= _CONSISTENCY_FIELDS.get(issue.code, set())
    return found


def effective_confidences(fields: dict[str, FieldResult], issues: Sequence[Issue]) -> dict[str, float | None]:
    flagged = inconsistent_fields(issues)
    return {
        name: None
        if f.is_missing
        else confidence.effective_confidence(f.confidence, inconsistent=name in flagged)
        for name, f in fields.items()
    }


def field_status(
    field: FieldResult, effective: float | None, issues: Sequence[Issue], config: ValidationConfig
) -> str:
    """missing | invalid | uncertain | ok."""
    if field.is_missing:
        return "missing"
    if field.is_invalid:
        return "invalid"
    has_warning = any(i.field == field.name and i.severity != WarningSeverity.INFO for i in issues)
    if has_warning or (effective is not None and effective < config.confidence_review):
        return "uncertain"
    return "ok"


def low_confidence_issues(
    document_type: DocumentType,
    fields: dict[str, FieldResult],
    effective: dict[str, float | None],
    issues: Sequence[Issue],
    config: ValidationConfig,
) -> list[Issue]:
    """A required field read with low confidence and no other warning explaining why."""
    explained = {i.field for i in issues if i.severity != WarningSeverity.INFO}
    found = []
    for name in REQUIRED_FIELDS[document_type]:
        f, score = fields[name], effective.get(name)
        if f.is_missing or f.is_invalid or score is None or name in explained:
            continue
        if score < config.confidence_review:
            found.append(
                Issue(
                    name,
                    CODE_LOW_CONFIDENCE,
                    f"{_LABELS[name].capitalize()} was read with low confidence ({score:.0%}).",
                )
            )
    return found


def overall_confidence(document_type: DocumentType, effective: dict[str, float | None], fields) -> float:
    """Mean effective confidence of the required fields; missing or invalid ones count as 0."""
    required = REQUIRED_FIELDS[document_type]
    scores = [
        0.0 if fields[n].is_missing or fields[n].is_invalid else (effective[n] or 0.0) for n in required
    ]
    return round(sum(scores) / len(scores), 3)


def needs_review(
    document_type: DocumentType,
    fields: dict[str, FieldResult],
    effective: dict[str, float | None],
    issues: Sequence[Issue],
    config: ValidationConfig,
) -> bool:
    """D-review rule: any warning/error, any required field missing/invalid, or any required field
    below the review confidence threshold."""
    if any(i.severity != WarningSeverity.INFO for i in issues):
        return True
    for name in REQUIRED_FIELDS[document_type]:
        f = fields[name]
        score = effective[name]
        if f.is_missing or f.is_invalid or score is None or score < config.confidence_review:
            return True
    return False
