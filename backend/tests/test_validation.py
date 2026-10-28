"""Validation rules, review decision, field status and confidence."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models import DocumentType, WarningSeverity
from app.services import confidence
from app.services.extraction.types import FIELD_NAMES, FieldResult, LineItemResult
from app.services.validation_service import (
    Issue,
    ValidationConfig,
    effective_confidences,
    field_level_issues,
    field_status,
    needs_review,
    overall_confidence,
    rule_issues,
)

CONFIG = ValidationConfig()
TODAY = date(2025, 6, 1)


def fields(**values) -> dict[str, FieldResult]:
    """Build a field set; every given field is valid with confidence 0.95."""
    out = {name: FieldResult(name) for name in FIELD_NAMES}
    for name, value in values.items():
        out[name] = FieldResult(name, str(value), value, 0.95, "regex")
    return out


def codes(issues) -> list[str]:
    return sorted(i.code for i in issues)


COMPLETE = dict(vendor_name="ACME", invoice_number="A-1", invoice_date=date(2025, 3, 1), total=D("54.00"))


def test_consistent_invoice_has_no_issues() -> None:
    f = fields(**COMPLETE, subtotal=D("50.00"), tax=D("4.00"))
    assert rule_issues(DocumentType.INVOICE, f, [], CONFIG, today=TODAY) == []


@pytest.mark.parametrize(
    ("doc_type", "missing", "expected"),
    [
        (DocumentType.INVOICE, "invoice_number", ["missing_required_field"]),
        (DocumentType.RECEIPT, "invoice_number", []),  # receipts often have no number
        (DocumentType.RECEIPT, "total", ["missing_required_field"]),
    ],
)
def test_required_fields_depend_on_document_type(doc_type, missing, expected) -> None:
    values = {k: v for k, v in COMPLETE.items() if k != missing}
    assert codes(rule_issues(doc_type, fields(**values), [], CONFIG, today=TODAY)) == expected


def test_unknown_document_type_is_flagged() -> None:
    assert "document_type_unknown" in codes(rule_issues(DocumentType.UNKNOWN, fields(**COMPLETE), [], CONFIG))


def test_totals_mismatch_beyond_tolerance_only() -> None:
    within = fields(**{**COMPLETE, "total": D("54.01")}, subtotal=D("50.00"), tax=D("4.00"))
    assert rule_issues(DocumentType.INVOICE, within, [], CONFIG, today=TODAY) == []

    off = fields(**{**COMPLETE, "total": D("64.00")}, subtotal=D("50.00"), tax=D("4.00"))
    [issue] = rule_issues(DocumentType.INVOICE, off, [], CONFIG, today=TODAY)
    assert issue.code == "totals_mismatch" and issue.field == "total"
    assert issue.message == "Totals don't add up: subtotal 50.00 + tax 4.00 = 54.00, but the total is 64.00."


def test_discount_is_subtracted() -> None:
    f = fields(**{**COMPLETE, "total": D("49.00")}, subtotal=D("50.00"), tax=D("4.00"), discount=D("5.00"))
    assert rule_issues(DocumentType.INVOICE, f, [], CONFIG, today=TODAY) == []


def test_line_items_checked_against_subtotal_and_their_own_arithmetic() -> None:
    items = [
        LineItemResult("A", D("2"), D("10.00"), D("20.00"), 0.9, 1),
        LineItemResult("B", D("3"), D("5.00"), D("16.00"), 0.9, 1),  # 3 × 5 ≠ 16
    ]
    f = fields(**{**COMPLETE, "total": D("40.00")}, subtotal=D("40.00"))
    issues = rule_issues(DocumentType.INVOICE, f, items, CONFIG, today=TODAY)
    assert codes(issues) == ["line_item_arithmetic", "line_items_mismatch"]
    arithmetic = next(i for i in issues if i.code == "line_item_arithmetic")
    assert arithmetic.field == "line_items[2]"
    assert "Line items add up to 36.00, but the subtotal is 40.00." in [i.message for i in issues]


def test_line_items_without_subtotal_compare_to_total_before_tax() -> None:
    items = [LineItemResult("A", D("1"), D("50.00"), D("50.00"), 0.9, 1)]
    f = fields(**COMPLETE, tax=D("4.00"))  # total 54 − tax 4 = 50 ✓
    assert rule_issues(DocumentType.INVOICE, f, items, CONFIG, today=TODAY) == []


def test_date_rules() -> None:
    f = fields(**{**COMPLETE, "invoice_date": date(2025, 9, 1)}, due_date=date(2025, 8, 1))
    assert codes(rule_issues(DocumentType.INVOICE, f, [], CONFIG, today=TODAY)) == [
        "date_in_future",
        "due_before_invoice_date",
    ]
    old = fields(**{**COMPLETE, "invoice_date": date(1985, 1, 1)})
    assert codes(rule_issues(DocumentType.INVOICE, old, [], CONFIG, today=TODAY)) == ["date_implausible"]


def test_negative_total_is_an_error() -> None:
    [issue] = rule_issues(
        DocumentType.INVOICE, fields(**{**COMPLETE, "total": D("-5.00")}), [], CONFIG, today=TODAY
    )
    assert issue.code == "negative_amount" and issue.severity == WarningSeverity.ERROR


def test_validation_never_modifies_values() -> None:
    f = fields(**{**COMPLETE, "total": D("64.00")}, subtotal=D("50.00"), tax=D("4.00"))
    before = {n: (x.value, x.normalized, x.confidence) for n, x in f.items()}
    rule_issues(DocumentType.INVOICE, f, [], CONFIG, today=TODAY)
    assert {n: (x.value, x.normalized, x.confidence) for n, x in f.items()} == before


def test_field_level_issue_messages() -> None:
    f = fields()
    f["invoice_date"] = FieldResult(
        "invoice_date",
        "03/04/2025",
        date(2025, 4, 3),
        0.66,
        "regex",
        flags={"ambiguous_date"},
        notes={"alternative": "2025-03-04"},
    )
    [issue] = field_level_issues(f)
    assert (
        issue.message
        == "Invoice date '03/04/2025' is ambiguous: read as 2025-04-03, but it could also be 2025-03-04."
    )


# --- Review decision, status, confidence -------------------------------------


def _review(f, issues=()):
    effective = effective_confidences(f, list(issues))
    return needs_review(DocumentType.INVOICE, f, effective, list(issues), CONFIG)


def test_review_rule() -> None:
    assert _review(fields(**COMPLETE)) is False
    assert _review(fields(**COMPLETE), [Issue("total", "totals_mismatch", "x")]) is True
    assert (
        _review(fields(**COMPLETE), [Issue("tax", "tax_summed", "x", WarningSeverity.INFO)]) is False
    )  # info only

    low = fields(**COMPLETE)
    low["vendor_name"].confidence = 0.55  # below the 0.60 review threshold
    assert _review(low) is True

    invalid = fields(**COMPLETE)
    invalid["invoice_date"] = FieldResult("invoice_date", "31/02/2025", None, 0.15, "regex")
    assert _review(invalid) is True


def test_field_status_values() -> None:
    f = fields(total=D("10.00"), vendor_name="ACME")
    f["invoice_date"] = FieldResult("invoice_date", "31/02/2025", None, 0.15, "regex")
    f["vendor_name"].confidence = 0.5
    issues = [Issue("tax", "ambiguous_amount", "x")]
    f["tax"] = FieldResult("tax", "1.234", D("1234.00"), 0.9, "regex")
    status = {
        n: field_status(f[n], f[n].confidence, issues, CONFIG)
        for n in ("total", "invoice_number", "invoice_date", "vendor_name", "tax")
    }
    assert status == {
        "total": "ok",
        "invoice_number": "missing",
        "invoice_date": "invalid",
        "vendor_name": "uncertain",  # low confidence
        "tax": "uncertain",  # has a warning
    }


def test_consistency_failure_lowers_effective_not_stored_confidence() -> None:
    f = fields(**{**COMPLETE, "total": D("64.00")}, subtotal=D("50.00"), tax=D("4.00"))
    issues = rule_issues(DocumentType.INVOICE, f, [], CONFIG, today=TODAY)
    effective = effective_confidences(f, issues)
    assert effective["total"] == pytest.approx(0.95 * 0.7, abs=0.001)
    assert effective["invoice_number"] == 0.95  # not involved
    assert f["total"].confidence == 0.95  # stored value untouched: re-validation is idempotent


def test_overall_confidence_counts_missing_required_as_zero() -> None:
    f = fields(**{k: v for k, v in COMPLETE.items() if k != "invoice_number"})
    assert overall_confidence(DocumentType.INVOICE, effective_confidences(f, []), f) == pytest.approx(
        0.95 * 3 / 4, abs=0.001
    )  # rounded to 3 dp


@pytest.mark.parametrize(
    ("score", "level"), [(0.9, "high"), (0.85, "high"), (0.7, "medium"), (0.59, "low"), (None, None)]
)
def test_confidence_levels(score, level) -> None:
    assert confidence.level(score, high=0.85, medium=0.60) == level
