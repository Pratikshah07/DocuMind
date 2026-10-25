"""Real Tesseract runs. Skipped when the binary is not installed."""

import numpy as np
import pytest

from app.services.ocr import OCRUnavailableError, TesseractOCR
from app.services.ocr.tesseract import resolve_tesseract_cmd
from tests.conftest import requires_tesseract
from tests.samples import render_text_image


@requires_tesseract
def test_recognizes_rendered_invoice_text() -> None:
    result = TesseractOCR().extract_text(np.asarray(render_text_image()), page_number=1)

    assert result.page_number == 1
    for token in ("NORTHWIND", "INV-2041", "2025-03-18", "54.00"):
        assert token in result.text
    assert 0.8 <= result.confidence <= 1.0  # clean render: high engine confidence
    assert all(w.bbox[2] > 0 and w.bbox[3] > 0 for w in result.words)
    first_line = [w.text for w in result.words if w.line == 0]
    assert first_line == ["NORTHWIND", "TRADING", "CO"]


@requires_tesseract
def test_blank_image_yields_no_text() -> None:
    result = TesseractOCR().extract_text(np.full((600, 600), 255, np.uint8), page_number=3)
    assert result.text == ""
    assert result.confidence is None
    assert result.words == []


@requires_tesseract
def test_check_available_reports_version() -> None:
    assert TesseractOCR().check_available().startswith("tesseract 5")


def test_missing_binary_is_reported_as_unavailable(tmp_path) -> None:
    ocr = TesseractOCR(cmd=str(tmp_path / "nope" / "tesseract.exe"))
    with pytest.raises(OCRUnavailableError):
        ocr.check_available()
    with pytest.raises(OCRUnavailableError):
        ocr.extract_text(np.zeros((10, 10), np.uint8), page_number=1)


def test_resolve_rejects_nonexistent_configured_path(tmp_path) -> None:
    assert resolve_tesseract_cmd(str(tmp_path / "missing.exe")) is None
