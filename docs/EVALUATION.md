# Extraction evaluation

How well the deterministic extractor reads the **synthetic** sample documents in
`backend/samples/`, measured against hand-labelled ground truth.

**What this is not:** a general accuracy figure. The 17 samples are synthetic, and the
rules were developed against them, so these numbers are a regression baseline. They are
not a prediction of how real-world invoices will be read. No accuracy claim about real
documents is made anywhere in DocuMind.

## Method

- Ground truth: `backend/samples/ground_truth.json`, written from the document text
  (`backend/tests/invoice_texts.py`), never from extractor output.
  - `null` means the document has no such value, so extracting one counts as a false positive.
  - `"__skip__"` marks values that are ambiguous by design (the `03/04/2025` date, the two
    conflicting totals, a bare `$`); they are not scored.
  - Addresses are free text and are not scored.
- Pipeline: `scripts/evaluate_extraction.py` runs the production page reader (PDF text
  layer, or preprocessing + Tesseract OCR) and the rule-based extractor. No database.
- Scoring (`app/services/evaluation.py`):
  - field values are compared after normalization (amounts as decimals, ISO dates,
    case- and whitespace-insensitive text);
  - line-item rows are matched by total, then description;
  - cell accuracy covers description, quantity, unit price and total over matched rows.
- Regression gate: `tests/test_evaluation.py` requires every text-layer sample to match
  exactly, and the OCR samples to read at least 90% of present values with no false positives.

Reproduce:

```
cd backend
python scripts/evaluate_extraction.py            # add --details to list every wrong value
```

## Before this pass (baseline, same 17 samples)

Measured before the extraction changes on branch `feature/engineering-pass`. The four new
samples (14–17) and three new fields (buyer, PO number, vendor tax ID) were added first,
so the baseline includes the cases the old rules could not handle.

| Metric | Result |
|---|---|
| Fields present in the document and read correctly | 107/119 (89.9%) |
| False positives | 1 (a vendor guessed on a non-invoice) |
| Line-item row precision / recall | 100.0% / 88.9% |
| Line-item cell accuracy (matched rows) | 87.5% (a VAT column read as the unit price) |

Misses before the changes:
- buyer, PO number and vendor tax ID were not extracted;
- the vendor in a two-column header was misread as a merged address line;
- `CARD` was not recognised as a payment method;
- till-receipt lines (`2 x Oat milk @ 2.10`, weighed items, single-price lines) were dropped;
- a wrapped description line containing numbers was lost.

## After

| Metric | Result |
|---|---|
| Samples | 17 |
| Document type correct | 100.0% |
| Fields correct (all scored) | 218/218 (100.0%) |
| Fields present in the document and read correctly | 119/119 (100.0%) |
| False positives (value extracted where the document has none) | 0 |
| Line-item row precision / recall | 100.0% / 100.0% |
| Line-item cell accuracy (matched rows) | 100.0% |

| Sample | Pages (OCR) | Fields wrong | Rows matched/expected/extracted | Read ms | Extract ms | Peak MB | Status |
|---|---|---|---|---|---|---|---|
| 01_invoice_standard.pdf | 1 (0) | — | 2/2/2 | 407 | 87.3 | 6.0 | COMPLETED |
| 02_receipt_coffee.pdf | 1 (0) | — | 2/2/2 | 359 | 16.4 | 6.0 | COMPLETED |
| 03_invoice_gst_india.pdf | 1 (0) | — | 2/2/2 | 319 | 8.0 | 6.0 | COMPLETED |
| 04_invoice_eu_format.pdf | 1 (0) | — | 1/1/1 | 244 | 6.9 | 6.0 | NEEDS_REVIEW |
| 05_invoice_multi_page.pdf | 2 (0) | — | 5/5/5 | 524 | 10.2 | 6.1 | COMPLETED |
| 06_missing_invoice_number.pdf | 1 (0) | — | 1/1/1 | 214 | 3.5 | 6.0 | NEEDS_REVIEW |
| 07_totals_dont_add_up.pdf | 1 (0) | — | 2/2/2 | 235 | 5.3 | 6.0 | NEEDS_REVIEW |
| 08_ambiguous_date.pdf | 1 (0) | — | 0/0/0 | 215 | 5.4 | 6.0 | NEEDS_REVIEW |
| 09_malformed_values.pdf | 1 (0) | — | 0/0/0 | 241 | 3.9 | 6.0 | NEEDS_REVIEW |
| 10_conflicting_totals.pdf | 1 (0) | — | 0/0/0 | 244 | 3.1 | 6.0 | NEEDS_REVIEW |
| 11_not_an_invoice.pdf | 1 (0) | — | 0/0/0 | 211 | 2.3 | 6.0 | NEEDS_REVIEW |
| 12_scanned_invoice.pdf | 1 (1) | — | 2/2/2 | 2177 | 8.6 | 48.2 | COMPLETED |
| 13_invoice_photo.jpg | 1 (1) | — | 1/1/1 | 2750 | 4.9 | 15.5 | COMPLETED |
| 14_invoice_tax_column.pdf | 1 (0) | — | 2/2/2 | 329 | 9.7 | 6.0 | COMPLETED |
| 15_invoice_two_column.pdf | 1 (0) | — | 2/2/2 | 271 | 8.0 | 6.0 | COMPLETED |
| 16_receipt_compact.pdf | 1 (0) | — | 3/3/3 | 280 | 8.9 | 6.0 | NEEDS_REVIEW |
| 17_low_res_scan.pdf | 1 (1) | — | 2/2/2 | 1776 | 4.6 | 48.2 | COMPLETED |

Environment: Windows-11-10.0.26200-SP0, Python 3.14.6, Intel64 Family 6 Model 140 Stepping 1, GenuineIntel, Tesseract tesseract 5.4.0.20240606.

Timings are single runs on a developer laptop (wall clock, including PDF rendering and
preview generation). Tesseract runs as a separate process, so its memory is not included
in "Peak MB" (Python allocations only, via `tracemalloc`). Production (Render free tier,
shared CPU) will be slower. See `docs/BENCHMARKS.md`.

## Known limitations

- Per-line tax and discount columns are recognised so that they are not misread as
  prices, but they are not stored. Line items keep quantity, unit price and total.
- Bounding boxes are stored for text-layer pages, and for OCR pages that were not
  rotated by deskew. Skewed photos get no boxes rather than misplaced ones.
- No LLM is used. The rules generalise to similar layouts, but unfamiliar layouts
  should be expected to need review.
