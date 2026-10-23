import hashlib
import io

import pytest

from app.core.errors import PayloadTooLargeError, UnsupportedMediaError, ValidationFailedError
from app.services.upload_validation import JPEG, PDF, PNG, sanitize_filename, validate_upload
from tests.samples import make_jpeg, make_pdf, make_png

MB = 1024 * 1024


def _validate(content: bytes, filename: str, mime: str | None = None, max_size: int = MB):
    return validate_upload(
        filename=filename, declared_mime_type=mime, stream=io.BytesIO(content), max_size=max_size
    )


@pytest.mark.parametrize(
    ("content", "filename", "mime", "kind"),
    [
        (make_pdf(), "invoice.pdf", "application/pdf", PDF),
        (make_png(), "receipt.png", "image/png", PNG),
        (make_jpeg(), "receipt.jpg", "image/jpeg", JPEG),
        (make_jpeg(), "receipt.JPEG", "image/jpg", JPEG),
    ],
)
def test_accepts_supported_files(content: bytes, filename: str, mime: str, kind) -> None:
    result = _validate(content, filename, mime)

    assert result.kind is kind
    assert result.size_bytes == len(content)
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.content.read() == content  # positioned at the start, full copy


@pytest.mark.parametrize("mime", [None, "", "application/octet-stream", "application/pdf; charset=binary"])
def test_generic_or_parameterised_content_type_is_accepted(mime: str | None) -> None:
    assert _validate(make_pdf(), "a.pdf", mime).mime_type == "application/pdf"


@pytest.mark.parametrize("filename", ["notes.txt", "malware.exe", "archive.pdf.zip", "no-extension", ""])
def test_rejects_unsupported_extensions(filename: str) -> None:
    with pytest.raises(UnsupportedMediaError) as exc:
        _validate(make_pdf(), filename)
    assert exc.value.code == "unsupported_file_type"


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (b"<html><script>alert(1)</script></html>", "invoice.pdf"),
        (b"MZ\x90\x00\x03\x00\x00\x00", "invoice.pdf"),  # Windows executable header
        (b"GIF89a\x01\x00\x01\x00", "receipt.png"),
        (b"just some text", "receipt.jpg"),
    ],
)
def test_rejects_content_that_is_not_a_supported_type(content: bytes, filename: str) -> None:
    with pytest.raises(UnsupportedMediaError) as exc:
        _validate(content, filename)
    assert exc.value.code == "unrecognized_file_content"


@pytest.mark.parametrize(
    ("content", "filename"),
    [(make_pdf(), "receipt.png"), (make_png(), "invoice.pdf"), (make_jpeg(), "receipt.png")],
)
def test_rejects_extension_that_does_not_match_content(content: bytes, filename: str) -> None:
    with pytest.raises(UnsupportedMediaError) as exc:
        _validate(content, filename)
    assert exc.value.code == "file_type_mismatch"


def test_rejects_declared_mime_type_that_does_not_match_content() -> None:
    with pytest.raises(UnsupportedMediaError) as exc:
        _validate(make_png(), "receipt.png", "application/pdf")
    assert exc.value.code == "file_type_mismatch"
    assert exc.value.details["detected_mime_type"] == "image/png"


def test_rejects_empty_file() -> None:
    with pytest.raises(ValidationFailedError) as exc:
        _validate(b"", "invoice.pdf")
    assert exc.value.code == "empty_file"


def test_size_limit_is_inclusive() -> None:
    content = make_pdf()
    assert _validate(content, "a.pdf", max_size=len(content)).size_bytes == len(content)

    with pytest.raises(PayloadTooLargeError) as exc:
        _validate(content, "a.pdf", max_size=len(content) - 1)
    assert exc.value.details == {"max_bytes": len(content) - 1}


def test_oversized_stream_is_not_read_to_the_end() -> None:
    class EndlessPdf(io.RawIOBase):
        def __init__(self) -> None:
            self.served = 0

        def readable(self) -> bool:
            return True

        def read(self, size: int = -1) -> bytes:
            chunk = (b"%PDF-" if self.served == 0 else b"") + b"0" * (size - (5 if self.served == 0 else 0))
            self.served += len(chunk)
            return chunk

    stream = EndlessPdf()
    with pytest.raises(PayloadTooLargeError):
        validate_upload(filename="big.pdf", declared_mime_type=None, stream=stream, max_size=MB)
    assert stream.served <= MB + 64 * 1024  # stopped within one chunk of the limit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\Windows\\System32\\evil.pdf", "evil.pdf"),
        ("C:\\Users\\me\\Invoices\\INV 001.pdf", "INV 001.pdf"),
        ("..pdf", "pdf"),
        ("inv\x00oice\x1f.pdf", "inv_oice_.pdf"),
        ('a<b>c:d"e|f?g*h.pdf', "a_b_c_d_e_f_g_h.pdf"),
        ("  spaced    out  .png ", "spaced out .png"),
        ("ｉｎｖｏｉｃｅ.pdf", "invoice.pdf"),  # full-width letters normalised (NFKC)
        (None, ""),
    ],
)
def test_sanitize_filename(raw: str | None, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_but_keeps_extension() -> None:
    name = sanitize_filename("x" * 400 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")


def test_traversal_filename_is_reduced_to_basename_on_upload() -> None:
    assert _validate(make_pdf(), "../../secret/invoice.pdf").filename == "invoice.pdf"
