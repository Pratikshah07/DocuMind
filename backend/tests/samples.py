"""Synthetic sample documents, generated in code. No real documents or personal data.

These are real, decodable files (PyMuPDF / Pillow / OpenCV), so parsing and OCR
tests exercise actual decoding rather than just file signatures.
"""

import io
import struct
import zlib

import cv2
import numpy as np
import pymupdf
from PIL import Image

INVOICE_LINES = [
    "NORTHWIND TRADING CO",
    "INVOICE  INV-2041",
    "Invoice date: 2025-03-18",
    "Widget assembly kit   4 x 12.50   50.00",
    "Subtotal  50.00",
    "Tax  4.00",
    "TOTAL DUE  54.00",
]


def _text_page(doc: pymupdf.Document, lines: list[str], fontsize: float = 16) -> None:
    page = doc.new_page(width=612, height=792)
    y = 90
    for line in lines:
        page.insert_text((72, y), line, fontsize=fontsize, fontname="helv")
        y += fontsize * 2.2


def render_text_image(lines: list[str] = INVOICE_LINES, *, dpi: int = 200) -> Image.Image:
    """Render lines of text to an RGB image (a clean 'scan')."""
    doc = pymupdf.open()
    _text_page(doc, lines)
    pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return image


def make_pdf(*pages: list[str]) -> bytes:
    """PDF with a real text layer; one page per list of lines (default: one invoice page)."""
    doc = pymupdf.open()
    for lines in pages or (INVOICE_LINES,):
        _text_page(doc, lines)
    data = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return data


def make_scanned_pdf(*pages: list[str] | None, dpi: int = 200) -> bytes:
    """PDF whose pages are images only (no text layer). ``None`` = a blank scanned page."""
    doc = pymupdf.open()
    for lines in pages or (INVOICE_LINES,):
        image = render_text_image(lines, dpi=dpi) if lines else Image.new("RGB", (1700, 2200), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=buffer.getvalue())
    data = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return data


def make_mixed_pdf() -> bytes:
    """Page 1 has a text layer, page 2 is scanned."""
    doc = pymupdf.open(stream=make_pdf(), filetype="pdf")
    scanned = pymupdf.open(
        stream=make_scanned_pdf(["PAGE TWO SCANNED", "Freight charge  20.00"]), filetype="pdf"
    )
    doc.insert_pdf(scanned)
    data = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    scanned.close()
    return data


def make_encrypted_pdf() -> bytes:
    doc = pymupdf.open(stream=make_pdf(), filetype="pdf")
    buffer = io.BytesIO()
    doc.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", user_pw="user-secret")
    doc.close()
    return buffer.getvalue()


def make_zero_page_pdf() -> bytes:
    """Structurally valid PDF whose page tree is empty (PyMuPDF refuses to write one, so built by hand)."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [] /Count 0 >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def corrupt_pdf() -> bytes:
    """Valid PDF signature, garbage body."""
    return b"%PDF-1.7\n" + bytes(range(256)) * 20


def _encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def make_png(lines: list[str] = INVOICE_LINES) -> bytes:
    return _encode(render_text_image(lines), "PNG")


def make_jpeg(lines: list[str] = INVOICE_LINES, *, quality: int = 90) -> bytes:
    return _encode(render_text_image(lines), "JPEG", quality=quality)


def make_photo_jpeg(lines: list[str] = INVOICE_LINES, *, angle: float = 4.0, seed: int = 7) -> bytes:
    """A 'phone photo' receipt: rotated, uneven lighting, sensor noise, JPEG artefacts."""
    image = np.asarray(render_text_image(lines, dpi=150)).astype(np.float32)
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    image = cv2.warpAffine(image, matrix, (width, height), borderValue=(255, 255, 255))
    gradient = np.linspace(0.75, 1.0, width, dtype=np.float32)[None, :, None]  # shadow on the left
    noise = np.random.default_rng(seed).normal(0, 12, image.shape).astype(np.float32)
    photo = np.clip(image * gradient + noise, 0, 255).astype(np.uint8)
    return _encode(Image.fromarray(photo), "JPEG", quality=70)


def make_blank_png(width: int = 800, height: int = 1000) -> bytes:
    return _encode(Image.new("RGB", (width, height), "white"), "PNG")


def make_tiny_png(width: int = 4, height: int = 4) -> bytes:
    """Minimal valid grayscale PNG, built byte by byte (no image library)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_rotated_exif_jpeg() -> bytes:
    """Landscape pixels with EXIF Orientation=6 ('rotate 90° CW to display')."""
    image = Image.new("RGB", (400, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6
    return _encode(image, "JPEG", exif=exif.tobytes())


def truncate(data: bytes, keep: float = 0.5) -> bytes:
    return data[: int(len(data) * keep)]
