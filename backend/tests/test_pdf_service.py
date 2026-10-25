import pytest

from app.services.pdf_service import PdfDocument
from app.services.processing_errors import ProcessingError
from tests.samples import (
    corrupt_pdf,
    make_encrypted_pdf,
    make_mixed_pdf,
    make_pdf,
    make_scanned_pdf,
    make_zero_page_pdf,
    truncate,
)

MAX_PIXELS = 40_000_000


def open_pdf(data: bytes, max_pages: int = 50) -> PdfDocument:
    return PdfDocument(data, max_pages=max_pages)


def test_reads_text_layer_in_reading_order() -> None:
    with open_pdf(make_pdf()) as pdf:
        assert pdf.page_count == 1
        text = pdf.text(0)
    # sort=True keeps vertical gaps as blank lines and may collapse runs of spaces; compare normalized.
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    assert lines[:2] == ["NORTHWIND TRADING CO", "INVOICE INV-2041"]
    assert lines[-1] == "TOTAL DUE 54.00"


def test_multi_page_text_is_kept_per_page() -> None:
    with open_pdf(make_pdf(["Page one invoice"], ["Page two terms"], ["Page three total"])) as pdf:
        texts = [pdf.text(i).strip() for i in range(pdf.page_count)]
    assert texts == ["Page one invoice", "Page two terms", "Page three total"]


def test_scanned_pdf_has_no_text_layer() -> None:
    with open_pdf(make_scanned_pdf()) as pdf:
        assert pdf.text(0).strip() == ""


def test_mixed_pdf_has_text_only_on_first_page() -> None:
    with open_pdf(make_mixed_pdf()) as pdf:
        assert pdf.page_count == 2
        assert "NORTHWIND" in pdf.text(0)
        assert pdf.text(1).strip() == ""


def test_render_produces_page_sized_image() -> None:
    with open_pdf(make_pdf()) as pdf:
        image = pdf.render(0, dpi=100, max_pixels=MAX_PIXELS)
    assert image.mode == "RGB"
    assert image.size == (850, 1100)  # US Letter 8.5x11 in at 100 dpi


def test_render_lowers_dpi_to_respect_pixel_budget() -> None:
    with open_pdf(make_pdf()) as pdf:
        image = pdf.render(0, dpi=300, max_pixels=1_000_000)
    assert image.width * image.height <= 1_000_000
    assert image.width > 0


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (corrupt_pdf(), "corrupt_pdf"),
        (b"%PDF-1.4\n", "corrupt_pdf"),
        (truncate(make_pdf(), 0.1), "corrupt_pdf"),
        (make_encrypted_pdf(), "encrypted_pdf"),
        (make_zero_page_pdf(), "empty_document"),
    ],
    ids=["garbage", "header-only", "truncated", "encrypted", "zero-pages"],
)
def test_bad_pdfs_raise_processing_errors(data: bytes, code: str) -> None:
    with pytest.raises(ProcessingError) as exc:
        open_pdf(data)
    assert exc.value.code == code
    # User-facing text is generic: no library messages, no file internals.
    assert "pymupdf" not in exc.value.user_message.lower()


def test_page_limit() -> None:
    with pytest.raises(ProcessingError) as exc:
        open_pdf(make_pdf(["a"], ["b"], ["c"]), max_pages=2)
    assert exc.value.code == "too_many_pages"
    assert "3 pages" in exc.value.user_message
