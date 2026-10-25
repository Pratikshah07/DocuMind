"""PDF parsing with PyMuPDF: open/validate, read text layers, render pages."""

import math
from types import TracebackType

import pymupdf
from PIL import Image

from app.services.processing_errors import ProcessingError, corrupt_pdf

# MuPDF prints recoverable errors/warnings to stderr; they can quote document internals.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

_POINTS_PER_INCH = 72


class PdfDocument:
    """An opened, validated PDF. Use as a context manager."""

    def __init__(self, content: bytes, *, max_pages: int) -> None:
        try:
            doc = pymupdf.open(stream=content, filetype="pdf")
        except Exception as exc:  # FileDataError, RuntimeError, ValueError depending on the damage
            raise corrupt_pdf(type(exc).__name__) from exc
        if doc.needs_pass or doc.is_encrypted:
            doc.close()
            raise ProcessingError("encrypted_pdf", "The PDF is password-protected. Upload an unlocked copy.")
        if doc.page_count == 0:
            doc.close()
            raise ProcessingError("empty_document", "The PDF has no pages.")
        if doc.page_count > max_pages:
            count = doc.page_count
            doc.close()
            raise ProcessingError(
                "too_many_pages",
                f"The PDF has {count} pages; the limit is {max_pages}.",
                detail=f"page_count={count}",
            )
        self._doc = doc

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self._doc.close()

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def text(self, index: int) -> str:
        """Text layer of a 0-based page ('' for scanned pages)."""
        try:
            return self._doc[index].get_text("text", sort=True)
        except Exception as exc:
            raise corrupt_pdf(f"page {index + 1}: {type(exc).__name__}") from exc

    def render(self, index: int, *, dpi: int, max_pixels: int) -> Image.Image:
        """Render a 0-based page to an RGB image, lowering the DPI if the result would exceed max_pixels."""
        try:
            page = self._doc[index]
            width_in = page.rect.width / _POINTS_PER_INCH
            height_in = page.rect.height / _POINTS_PER_INCH
            pixels_at_dpi = (width_in * dpi) * (height_in * dpi)
            if pixels_at_dpi > max_pixels:
                dpi = max(36, math.floor(math.sqrt(max_pixels / (width_in * height_in))))
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except ProcessingError:
            raise
        except Exception as exc:
            raise corrupt_pdf(f"render page {index + 1}: {type(exc).__name__}") from exc
