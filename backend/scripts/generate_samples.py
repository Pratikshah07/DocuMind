"""Generate the development sample dataset into backend/samples/.

All content is synthetic (fictional companies, people and amounts). The same
texts drive the automated tests (tests/invoice_texts.py), so the samples and the
tests can't drift apart.

    cd backend
    python scripts/generate_samples.py
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests import invoice_texts as T  # noqa: E402
from tests.samples import make_photo_jpeg, make_scanned_text_pdf, make_text_pdf  # noqa: E402

OUT = BACKEND / "samples"

# file name -> (bytes factory, what it demonstrates)
SAMPLES = {
    "01_invoice_standard.pdf": (
        lambda: make_text_pdf(T.STANDARD_INVOICE),
        "Complete, consistent invoice -> COMPLETED",
    ),
    "02_receipt_coffee.pdf": (lambda: make_text_pdf(T.RECEIPT), "Receipt with line items -> COMPLETED"),
    "03_invoice_gst_india.pdf": (lambda: make_text_pdf(T.GST_INVOICE), "CGST + SGST summed into tax (INR)"),
    "04_invoice_eu_format.pdf": (
        lambda: make_text_pdf(T.EU_INVOICE),
        "1.249,50 amounts; dd.mm.yyyy date flagged",
    ),
    "05_invoice_multi_page.pdf": (lambda: make_text_pdf(*T.MULTI_PAGE), "Table across 2 pages, discount"),
    "06_missing_invoice_number.pdf": (
        lambda: make_text_pdf(T.MISSING_NUMBER_AND_TAX),
        "Required field missing",
    ),
    "07_totals_dont_add_up.pdf": (lambda: make_text_pdf(T.TOTALS_MISMATCH), "Arithmetic warning"),
    "08_ambiguous_date.pdf": (lambda: make_text_pdf(T.AMBIGUOUS_DATE), "03/04/2025 read day-first, flagged"),
    "09_malformed_values.pdf": (lambda: make_text_pdf(T.MALFORMED), "31/02/2025 kept as invalid; no total"),
    "10_conflicting_totals.pdf": (
        lambda: make_text_pdf(T.CONFLICTING_TOTALS),
        "Two different totals flagged",
    ),
    "11_not_an_invoice.pdf": (lambda: make_text_pdf(T.NOT_AN_INVOICE), "Classified UNKNOWN -> review"),
    "12_scanned_invoice.pdf": (
        lambda: make_scanned_text_pdf(T.STANDARD_INVOICE),
        "Image-only PDF -> OCR path",
    ),
    "13_invoice_photo.jpg": (lambda: make_photo_jpeg(), "Skewed, noisy, shadowed photo -> OCR"),
    "14_invoice_tax_column.pdf": (
        lambda: make_text_pdf(T.TAX_COLUMN_INVOICE),
        "VAT column, wrapped description with numbers, PO number, VAT ID",
    ),
    "15_invoice_two_column.pdf": (
        lambda: make_text_pdf(T.TWO_COLUMN_INVOICE),
        "Vendor and Bill To side by side (interleaved columns)",
    ),
    "16_receipt_compact.pdf": (
        lambda: make_text_pdf(T.COMPACT_RECEIPT),
        "Till receipt: '2 x item @ price', weighed item, no table header",
    ),
    "17_low_res_scan.pdf": (
        lambda: make_scanned_text_pdf(T.TAX_COLUMN_INVOICE, dpi=100),
        "Low-resolution (100 dpi) scan of the tax-column invoice -> OCR",
    ),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = {}
    for name, (factory, purpose) in SAMPLES.items():
        data = factory()
        (OUT / name).write_bytes(data)
        manifest[name] = {"purpose": purpose, "bytes": len(data)}
        print(f"{name:34} {len(data):>8} B  {purpose}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
