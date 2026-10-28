from datetime import date
from decimal import Decimal as D

import pytest

from app.models import DocumentType
from app.services.classification_service import RuleBasedClassifier
from app.services.extraction.parsers import (
    DateOrder,
    find_amounts,
    find_currencies,
    find_date,
    parse_amount,
    parse_date,
)
from app.services.extraction.text import normalize_text, repair_numeric_token
from app.services.extraction.types import PageText
from tests import invoice_texts as T

# --- Amounts -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,249.50", D("1249.50")),  # US
        ("1.249,50", D("1249.50")),  # EU
        ("1 249.50", D("1249.50")),  # space grouping
        ("1'249.50", D("1249.50")),  # Swiss
        ("1,00,000.00", D("100000.00")),  # Indian lakh grouping
        ("12,50", D("12.50")),  # decimal comma
        ("$4,820", D("4820.00")),
        ("USD 54.00", D("54.00")),
        ("(12.00)", D("-12.00")),  # accounting negative
        ("-13.50", D("-13.50")),
        ("54.0O", D("54.00")),  # OCR: letter O for zero
        ("1O5.00", D("105.00")),
        ("1.249.50", D("1249.50")),  # OCR read the thousands comma as a dot
    ],
)
def test_parse_amount(raw: str, expected: D) -> None:
    parsed = parse_amount(raw)
    assert parsed is not None and parsed.value == expected and not parsed.ambiguous


def test_lone_dot_with_three_decimals_is_flagged_ambiguous() -> None:
    parsed = parse_amount("1.234")
    assert parsed.value == D("1234.00") and parsed.ambiguous and parsed.alternative == "1.234"


@pytest.mark.parametrize("raw", ["abc", "", "999999999999999.00", "1.2.3,4,5", "12,3456.00"])
def test_unparseable_amounts_return_none(raw: str) -> None:
    assert parse_amount(raw) is None


def test_find_amounts_ignores_percentages_and_dates() -> None:
    assert [r for r, _ in find_amounts("Tax (8%) 4.00")] == ["4.00"]
    assert [r for r, _ in find_amounts("Paid 2025-03-18 amount 54.00")] == ["54.00"]


# --- Dates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-03-18", date(2025, 3, 18)),
        ("18/03/2025", date(2025, 3, 18)),  # only one valid reading
        ("18 Mar 2025", date(2025, 3, 18)),
        ("March 18, 2025", date(2025, 3, 18)),
        ("5th March 2025", date(2025, 3, 5)),
        ("05-Feb-2025", date(2025, 2, 5)),
        ("18-Mar-25", date(2025, 3, 18)),
        ("2O25-O3-18", date(2025, 3, 18)),  # OCR noise
    ],
)
def test_parse_unambiguous_dates(raw: str, expected: date) -> None:
    for order in DateOrder:
        parsed = parse_date(raw, order)
        assert parsed is not None and parsed.value == expected and not parsed.ambiguous


@pytest.mark.parametrize(
    ("order", "expected", "other"),
    [("DMY", date(2025, 4, 3), "2025-03-04"), ("MDY", date(2025, 3, 4), "2025-04-03")],
)
def test_ambiguous_numeric_date_follows_configured_order_and_is_flagged(order, expected, other) -> None:
    parsed = parse_date("03/04/2025", DateOrder(order))
    assert parsed.value == expected and parsed.ambiguous and parsed.alternative == other


@pytest.mark.parametrize("raw", ["31/02/2025", "13/13/2025", "2025-02-30"])
def test_impossible_dates_are_found_but_invalid(raw: str) -> None:
    found = find_date(f"Invoice date {raw}", DateOrder.DMY)
    assert found is not None and found[0] == raw and found[1] is None


def test_month_names_inside_words_are_not_dates() -> None:
    assert find_date("summary 12 2025 marketing", DateOrder.DMY) is None


# --- Currency & text ---------------------------------------------------------


def test_find_currencies() -> None:
    assert find_currencies("Total USD 54.00 or $ 54 or Rs. 500 or €3") == [
        ("USD", "USD"),
        ("$", "USD"),
        ("Rs", "INR"),
        ("€", "EUR"),
    ]


def test_repair_only_touches_numeric_tokens() -> None:
    assert repair_numeric_token("54.0O") == "54.00"
    assert repair_numeric_token("SOLD") == "SOLD"
    assert repair_numeric_token("INV-2041") == "INV-2041"


def test_normalize_text_keeps_column_gaps_and_drops_blank_lines() -> None:
    assert normalize_text("A B      C\n\n  D—E  ") == "A B  C\nD-E"


# --- Classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (T.STANDARD_INVOICE, DocumentType.INVOICE),
        (T.GST_INVOICE, DocumentType.INVOICE),
        (T.RECEIPT, DocumentType.RECEIPT),
        (T.OCR_NOISY, DocumentType.INVOICE),  # "lNVOICE" still counts
        (T.NOT_AN_INVOICE, DocumentType.UNKNOWN),
    ],
    ids=["invoice", "gst-invoice", "receipt", "ocr-noisy", "meeting-notes"],
)
def test_classifier(text: str, expected: DocumentType) -> None:
    result = RuleBasedClassifier().classify([PageText(1, text)])
    assert result.document_type == expected
    assert 0 < result.confidence <= 1


def test_classifier_confidence_reflects_evidence() -> None:
    strong = RuleBasedClassifier().classify([PageText(1, T.STANDARD_INVOICE)]).confidence
    weak = RuleBasedClassifier().classify([PageText(1, "INVOICE\nTotal 10.00")]).confidence
    assert strong > weak
