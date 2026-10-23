"""Upload validation based on actual file content.

The file type is decided by the leading bytes ("magic numbers"), not by the
filename or the client's Content-Type. The extension and declared MIME type
must agree with what the bytes say, otherwise the upload is rejected.

The upload is copied into a spooled temporary file while hashing it and
counting bytes, so oversized uploads stop being read as soon as they cross the limit.
"""

import hashlib
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO

from app.core.errors import PayloadTooLargeError, UnsupportedMediaError, ValidationFailedError

_CHUNK = 64 * 1024
_SPOOL_IN_MEMORY = 1024 * 1024  # spill to disk above 1 MB


@dataclass(frozen=True)
class FileKind:
    mime_type: str
    extension: str  # canonical extension used for storage keys
    extensions: frozenset[str]  # accepted filename extensions
    aliases: frozenset[str]  # accepted declared Content-Types


PDF = FileKind(
    "application/pdf", ".pdf", frozenset({".pdf"}), frozenset({"application/pdf", "application/x-pdf"})
)
PNG = FileKind("image/png", ".png", frozenset({".png"}), frozenset({"image/png"}))
JPEG = FileKind(
    "image/jpeg", ".jpg", frozenset({".jpg", ".jpeg"}), frozenset({"image/jpeg", "image/jpg", "image/pjpeg"})
)

SUPPORTED_KINDS = (PDF, PNG, JPEG)
SUPPORTED_EXTENSIONS = frozenset().union(*(k.extensions for k in SUPPORTED_KINDS))
# Content-Types browsers/clients send when they don't know; treated as "not declared".
_GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}

_SIGNATURES: tuple[tuple[bytes, FileKind], ...] = (
    (b"%PDF-", PDF),
    (b"\x89PNG\r\n\x1a\n", PNG),
    (b"\xff\xd8\xff", JPEG),
)
_HEADER_LEN = max(len(sig) for sig, _ in _SIGNATURES)


@dataclass
class ValidatedUpload:
    filename: str  # sanitized display name; never used in storage paths
    kind: FileKind
    size_bytes: int
    sha256: str
    content: BinaryIO  # positioned at 0; caller must close

    @property
    def mime_type(self) -> str:
        return self.kind.mime_type


def detect_kind(header: bytes) -> FileKind | None:
    for signature, kind in _SIGNATURES:
        if header.startswith(signature):
            return kind
    return None


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(raw: str | None, *, max_length: int = 255) -> str:
    """Reduce a client-supplied filename to a safe display name.

    Strips any directory part (both ``/`` and ``\\``), control and reserved
    characters, and leading dots; the result is metadata only.
    """
    name = unicodedata.normalize("NFKC", raw or "")
    name = re.split(r"[/\\]", name)[-1]
    name = _UNSAFE_CHARS.sub("_", name)
    name = _WHITESPACE.sub(" ", name).strip().lstrip(".").strip()
    if len(name) > max_length:
        stem, ext = os.path.splitext(name)
        ext = ext if len(ext) <= 16 else ""
        name = stem[: max_length - len(ext)].rstrip() + ext
    return name


def validate_upload(
    *,
    filename: str | None,
    declared_mime_type: str | None,
    stream: BinaryIO,
    max_size: int,
) -> ValidatedUpload:
    safe_name = sanitize_filename(filename)
    extension = os.path.splitext(safe_name)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMediaError(
            "Unsupported file type. Upload a PDF, PNG, JPG or JPEG file.",
            details={"extension": extension or None, "allowed": sorted(SUPPORTED_EXTENSIONS)},
        )

    spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)  # noqa: SIM115 - returned to caller
    try:
        digest = hashlib.sha256()
        size = 0
        header = b""
        while chunk := stream.read(_CHUNK):
            size += len(chunk)
            if size > max_size:
                raise PayloadTooLargeError(
                    f"File is larger than the {max_size // (1024 * 1024)} MB limit.",
                    details={"max_bytes": max_size},
                )
            if len(header) < _HEADER_LEN:
                header += chunk[: _HEADER_LEN - len(header)]
            digest.update(chunk)
            spool.write(chunk)

        if size == 0:
            raise ValidationFailedError("The uploaded file is empty.", code="empty_file")

        kind = detect_kind(header)
        if kind is None:
            raise UnsupportedMediaError(
                "File content is not a valid PDF, PNG or JPEG.", code="unrecognized_file_content"
            )
        if extension not in kind.extensions:
            raise UnsupportedMediaError(
                "File extension does not match its content.",
                code="file_type_mismatch",
                details={"extension": extension, "detected_mime_type": kind.mime_type},
            )
        declared = (declared_mime_type or "").split(";")[0].strip().lower()
        if declared not in _GENERIC_MIME_TYPES and declared not in kind.aliases:
            raise UnsupportedMediaError(
                "Declared content type does not match the file content.",
                code="file_type_mismatch",
                details={"declared_mime_type": declared, "detected_mime_type": kind.mime_type},
            )

        spool.seek(0)
        return ValidatedUpload(
            filename=safe_name or f"document{kind.extension}",
            kind=kind,
            size_bytes=size,
            sha256=digest.hexdigest(),
            content=spool,
        )
    except BaseException:
        spool.close()
        raise
