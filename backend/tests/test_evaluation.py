"""Extraction quality on the labelled synthetic samples (samples/ground_truth.json).

A regression gate, not an accuracy claim: these are the documents the rules were
developed against. Text-layer samples must be read perfectly; OCR samples (Tesseract
output varies a little between versions) must read nearly every present value.
"""

import json
import sys
from pathlib import Path

import pytest

from app.services.evaluation import resolve_truth, score_sample, summarize
from tests.conftest import requires_tesseract

BACKEND = Path(__file__).resolve().parents[1]
TRUTH = json.loads((BACKEND / "samples" / "ground_truth.json").read_text(encoding="utf-8"))
OCR_SAMPLES = {"12_scanned_invoice.pdf", "13_invoice_photo.jpg", "17_low_res_scan.pdf"}
TEXT_SAMPLES = sorted(k for k in TRUTH if not k.startswith("_") and k not in OCR_SAMPLES)

sys.path.insert(0, str(BACKEND / "scripts"))
import evaluate_extraction  # noqa: E402


@pytest.mark.parametrize("sample", TEXT_SAMPLES)
def test_text_layer_samples_match_ground_truth(sample: str) -> None:
    [score], _ = evaluate_extraction.run([sample])
    assert score.type_correct
    assert [(f.name, f.expected, f.got) for f in score.field_errors] == []
    assert score.rows_matched == score.rows_expected == score.rows_extracted
    assert score.cells_correct == score.cells_total


@requires_tesseract
def test_ocr_samples_read_nearly_every_value() -> None:
    scores, _ = evaluate_extraction.run(sorted(OCR_SAMPLES))
    summary = summarize(scores)
    assert summary.present_correct / summary.present_fields >= 0.9, [s.field_errors for s in scores]
    assert summary.false_positives == 0


def test_scoring_rules() -> None:
    truth = {
        "document_type": "INVOICE",
        "fields": {"total": "10.00", "tax": None, "due_date": "__skip__"},
        "line_items": [{"description": "A", "quantity": "1", "unit_price": "10", "total": "10.00"}],
    }
    score = score_sample(
        "x",
        truth,
        document_type="INVOICE",
        fields={"total": 10.0, "tax": 1.0, "due_date": "2025-01-01"},
        line_items=[{"description": "a", "quantity": 1, "unit_price": 10, "total": 10}, {"total": 3}],
    )
    assert [(f.name, f.kind) for f in score.fields] == [("total", "correct"), ("tax", "false_positive")]
    assert (score.rows_matched, score.rows_expected, score.rows_extracted) == (1, 1, 2)
    assert score.cells_correct == score.cells_total == 4
    assert resolve_truth({"a": {"same_as": "b"}, "b": truth}, "a") is truth
