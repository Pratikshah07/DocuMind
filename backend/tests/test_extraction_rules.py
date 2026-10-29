"""Field and line-item extraction on representative and awkward documents (text level)."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.models import DocumentType
from app.services.extraction.types import (
    FIELD_NAMES,
    FLAG_AMBIGUOUS_DATE,
    FLAG_INVALID_FORMAT,
    FLAG_MULTIPLE_CANDIDATES,
    METHOD_LABEL,
    METHOD_PATTERN,
    PageText,
)
from app.services.extraction_service import ExtractionEngine, ExtractionOutcome
from tests import invoice_texts as T


def run(*pages: str, ocr_confidence: float | None = None) -> ExtractionOutcome:
    engine = ExtractionEngine()
    texts = [PageText(i + 1, text, ocr_confidence=ocr_confidence) for i, text in enumerate(pages)]
    return engine.validate(engine.extract(texts))


@pytest.mark.parametrize("case", sorted(T.CASES))
def test_representative_documents(case: str) -> None:
    text, expected = T.CASES[case]
    outcome = run(text)

    assert outcome.document_type == DocumentType(expected["type"])
    for name, value in expected.items():
        if name in FIELD_NAMES:
            assert outcome.fields[name].normalized == value, name
    assert len(outcome.line_items) == expected["items"]
    if "status" in expected:
        assert outcome.status.value == expected["status"], [i.message for i in outcome.issues]


def test_every_schema_field_is_present_even_when_missing() -> None:
    outcome = run(T.RECEIPT)
    assert set(outcome.fields) == set(FIELD_NAMES)
    assert outcome.fields["due_date"].is_missing and outcome.fields["due_date"].confidence is None


def test_raw_value_is_kept_exactly_as_printed() -> None:
    fields = run(T.STANDARD_INVOICE).fields
    assert fields["invoice_date"].value == "18/03/2025"  # normalized to a date, raw untouched
    assert fields["invoice_date"].normalized == date(2025, 3, 18)
    assert fields["total"].value == "4,820.00"
    assert fields["vendor_name"].method == METHOD_PATTERN and fields["total"].method == METHOD_LABEL


def test_card_digits_are_not_stored() -> None:
    payment = run(T.STANDARD_INVOICE).fields["payment_method"]
    assert payment.value == "VISA" and payment.normalized == "Visa"
    assert "4242" not in (payment.value or "")


def test_line_items_with_header_table() -> None:
    items = run(T.STANDARD_INVOICE).line_items
    assert [(i.description, i.quantity, i.unit_price, i.total) for i in items] == [
        ("Brand identity refinement", D("1"), D("2800.00"), D("2800.00")),
        ("Web design consultation", D("8"), D("212.50"), D("1700.00")),
    ]
    assert all(i.page_number == 1 and i.confidence >= 0.85 for i in items)


def test_line_items_span_pages_and_skip_repeated_header() -> None:
    outcome = run(*T.MULTI_PAGE)
    assert len(outcome.line_items) == 5
    assert [i.page_number for i in outcome.line_items] == [1, 1, 1, 2, 2]
    assert outcome.line_items[0].description == "Hex bolts M8 (box of 100)"  # digits inside description kept
    assert outcome.status.value == "COMPLETED"


def test_no_header_only_accepts_arithmetically_consistent_lines() -> None:
    lines = [
        "Corner Deli",
        "RECEIPT",
        "221B Baker Street 2 1.50 3.00",
        "Phone 555 0182 9",
        "Soup 2 x 4.25 8.50",
    ]
    text = "\n".join([*lines, "Total 8.50"])
    items = run(text).line_items
    # "221B Baker Street 2 1.50 3.00" is consistent too: a known limitation, but phone/address noise isn't.
    assert ("Soup", D("2"), D("4.25"), D("8.50")) in [
        (i.description, i.quantity, i.unit_price, i.total) for i in items
    ]
    assert all("Phone" not in (i.description or "") for i in items)


# --- Missing / invalid / ambiguous / conflicting ------------------------------


def test_missing_fields_stay_missing_nothing_is_invented() -> None:
    fields = run(T.MISSING_NUMBER_AND_TAX).fields
    assert fields["invoice_number"].is_missing
    assert fields["tax"].is_missing  # not assumed to be 0
    assert fields["currency"].is_missing  # not defaulted to USD
    assert fields["due_date"].is_missing  # not derived from payment terms


def test_unparseable_labelled_date_is_invalid_not_dropped() -> None:
    field = run(T.MALFORMED).fields["invoice_date"]
    assert field.value == "31/02/2025" and field.normalized is None and field.is_invalid
    assert FLAG_INVALID_FORMAT in field.flags and field.confidence == 0.15


def test_ambiguous_date_is_read_day_first_and_flagged() -> None:
    field = run(T.AMBIGUOUS_DATE).fields["invoice_date"]
    assert field.normalized == date(2025, 4, 3)
    assert FLAG_AMBIGUOUS_DATE in field.flags and field.notes["alternative"] == "2025-03-04"
    assert field.confidence < 0.7


def test_conflicting_totals_keep_the_last_and_flag() -> None:
    field = run(T.CONFLICTING_TOTALS).fields["total"]
    assert field.normalized == D("1080.00")
    assert FLAG_MULTIPLE_CANDIDATES in field.flags
    assert field.notes["candidates"] == "1080.00, 1200.00"


def test_grand_total_outranks_plain_total() -> None:
    fields = run("ACME LTD\nINVOICE\nInvoice No: A-1\nTotal 90.00\nShipping 10.00\nGrand Total 100.00").fields
    assert fields["total"].normalized == D("100.00")
    assert FLAG_MULTIPLE_CANDIDATES not in fields["total"].flags


def test_separately_labelled_taxes_are_summed_with_a_note() -> None:
    tax = run(T.GST_INVOICE).fields["tax"]
    assert tax.normalized == D("612.00") and tax.value == "306.00 + 306.00"
    assert tax.notes["summed_from"] == "CGST 9% 306.00 + SGST 9% 306.00"


def test_discount_magnitude_is_stored_and_sign_kept_in_raw() -> None:
    discount = run(*T.MULTI_PAGE).fields["discount"]
    assert discount.value == "-13.50" and discount.normalized == D("13.50")


@pytest.mark.parametrize(
    ("text", "field", "expected"),
    [
        (
            "ACME\nINVOICE\nInvoice Number\nINV-77\nTotal 5.00",
            "invoice_number",
            "INV-77",
        ),  # value below label
        ("ACME\nINVOICE\nInvoice date: 2025-01-02  Due date: 2025-02-01", "due_date", date(2025, 2, 1)),
        ("ACME\nINVOICE\nInvoice date: 2025-01-02  Due date: 2025-02-01", "invoice_date", date(2025, 1, 2)),
        ("ACME\nINVOICE\nInvoice No: SS/24-25/0193", "invoice_number", "SS/24-25/0193"),  # date-like inside
        ("ACME\nRECEIPT\n17/03/2025 08:42\nTotal 3.00", "invoice_date", date(2025, 3, 17)),  # unlabelled date
    ],
    ids=[
        "value-on-next-line",
        "two-labels-one-line-due",
        "two-labels-one-line-issue",
        "number-with-slashes",
        "unlabelled-date-fallback",
    ],
)
def test_layout_variants(text: str, field: str, expected) -> None:
    assert run(text).fields[field].normalized == expected


def test_ocr_noise_in_labels_and_values() -> None:
    fields = run(T.OCR_NOISY).fields
    assert fields["invoice_date"].value == "2O25-O3-18" and fields["invoice_date"].normalized == date(
        2025, 3, 18
    )
    assert fields["tax"].value == "4.0O" and fields["tax"].normalized == D("4.00")
    assert fields["subtotal"].normalized == D("50.00")  # "Subtota1"
    assert fields["total"].normalized == D("54.00")  # "T0TAL DUE"
    assert fields["vendor_name"].value == "NORTHWIND TRADING C0"  # names are never "corrected"


def test_ocr_confidence_lowers_field_confidence() -> None:
    clean = run(T.STANDARD_INVOICE).fields["total"].confidence
    scanned = run(T.STANDARD_INVOICE, ocr_confidence=0.5).fields["total"].confidence
    assert scanned < clean


def test_due_date_line_is_not_taken_as_invoice_date() -> None:
    fields = run("ACME\nINVOICE\nInvoice No: Z-9\nDue date: 2025-05-01\nTotal 1.00").fields
    assert fields["invoice_date"].is_missing
    assert fields["due_date"].normalized == date(2025, 5, 1)


def test_tax_registration_number_is_not_a_tax_amount() -> None:
    fields = run("ACME\nINVOICE\nInvoice No: Z-9\nTax ID: 12-3456789\nTotal 1.00").fields
    assert fields["tax"].is_missing


def test_single_space_table_columns_are_not_read_as_thousands() -> None:
    # Regression: PDF text layers separate columns with one space; "8 212.50" is qty 8 + 212.50.
    items = run(
        "ACME\nINVOICE\nDescription Qty Price Amount\nConsulting 8 212.50 1,700.00\nTotal 1,700.00"
    ).line_items
    assert [(i.quantity, i.unit_price, i.total) for i in items] == [(D("8"), D("212.50"), D("1700.00"))]


def test_space_grouped_amount_accepted_as_a_whole_labelled_value() -> None:
    fields = run("ACME\nFACTURE INVOICE\nInvoice No: F-1\nTotal: 1 249,50 EUR").fields
    assert fields["total"].normalized == D("1249.50") and fields["total"].value == "1 249,50"


# --- Harder layouts (Part 7) -------------------------------------------------------------


def test_tax_column_is_not_read_as_unit_price_and_wrapped_text_is_kept() -> None:
    outcome = run(T.TAX_COLUMN_INVOICE)
    first, second = outcome.line_items
    assert (first.quantity, first.unit_price, first.total) == (D("1"), D("1200.00"), D("1200.00"))
    assert first.description == "Quarterly data platform licence (April to June 2025, 25 seats)"
    assert (second.quantity, second.unit_price, second.total) == (D("2"), D("350.00"), D("700.00"))
    assert not any(i.code == "line_item_arithmetic" for i in outcome.issues)


def test_po_number_vendor_tax_id_and_buyer() -> None:
    fields = run(T.TAX_COLUMN_INVOICE).fields
    assert fields["po_number"].normalized == "PO-55120"
    assert fields["vendor_tax_id"].normalized == "GB 284 7731 06"
    assert fields["buyer_name"].normalized == "Corvid Health Partners"
    assert fields["tax"].normalized == D("380.00")  # "VAT No" is an identifier, not the VAT amount


def test_gstin_is_an_identifier_not_a_tax_amount() -> None:
    text = "Kiran Textiles\nGSTIN: 29ABCDE1234F1Z5\nInvoice No: KT-11\nInvoice Date: 2025-01-10\n"
    text += "Total  INR 590.00"
    fields = run(text).fields
    assert fields["vendor_tax_id"].normalized == "29ABCDE1234F1Z5"
    assert fields["tax"].is_missing


def test_buyer_tax_id_is_not_taken_as_the_vendors() -> None:
    text = "Kiran Textiles\nInvoice No: KT-11\nBill To:\nMeera Stores\nGSTIN: 33ZZZZZ9999Z1Z9\nTotal  590.00"
    assert run(text).fields["vendor_tax_id"].is_missing


def test_po_box_and_place_names_are_not_po_numbers() -> None:
    text = "Northstar Studio\nPO Box 12, Portland\nInvoice No: NS-1\nTotal  10.00"
    assert run(text).fields["po_number"].is_missing


def test_two_column_header_keeps_vendor_and_buyer_apart() -> None:
    fields = run(T.TWO_COLUMN_INVOICE).fields
    assert fields["vendor_name"].normalized == "Quillon Print Works"
    assert fields["buyer_name"].normalized == "Ostara Bakery"
    assert fields["billing_address"].normalized == "Ostara Bakery, 9 Mill Lane, Bath BA1 2HN"


def test_compact_receipt_lines_confirmed_by_the_total() -> None:
    outcome = run(T.COMPACT_RECEIPT)
    rows = [(i.description, i.quantity, i.unit_price, i.total) for i in outcome.line_items]
    assert rows == [
        ("Oat milk 1L", D("2"), D("2.10"), D("4.20")),
        ("Bananas", D("1.24"), D("1.10"), D("1.36")),
        ("Sourdough loaf", None, None, D("3.80")),
    ]
    assert outcome.fields["payment_method"].normalized == "Card"


def test_unconfirmed_single_price_lines_are_not_manufactured() -> None:
    # Same receipt with a total that does not match the lines: only arithmetic-proven rows survive.
    outcome = run(T.COMPACT_RECEIPT.replace("TOTAL  GBP 9.36", "TOTAL  GBP 12.00"))
    assert [i.description for i in outcome.line_items] == ["Oat milk 1L", "Bananas"]


def test_no_letterhead_guess_on_documents_that_are_not_invoices() -> None:
    assert run(T.NOT_AN_INVOICE).fields["vendor_name"].is_missing
