"""Document processing pipeline (Phase 3: text extraction).

    QUEUED job ─► PROCESSING  open + fully decode the file, read PDF text layers
                ─► OCR        (only if some page has no usable text) preprocess + OCR
                ─► COMPLETED  pages + previews saved atomically
       any error ─► FAILED    user-safe message on the document, code/detail on the job

Phase 4 inserts EXTRACTING and VALIDATING before COMPLETED.

Consistency rules:
- A job runs only from QUEUED, so a duplicate submit is a no-op.
- Page rows always reflect the *last successful* run: they are replaced in the
  same transaction that marks the document COMPLETED, and cleared when a run
  fails, so a FAILED document never shows stale pages.
- Preview files are written before that commit (keys are deterministic, so a
  retry overwrites them); previews no longer referenced are deleted after it.
"""

import io
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Document, DocumentPage, DocumentStatus, JobStatus, ProcessingJob, TextSource
from app.services.image_service import load_image
from app.services.ocr import OCRError, OCRResult, OCRService, OCRUnavailableError
from app.services.pdf_service import PdfDocument
from app.services.preprocessing_service import Preprocessor
from app.services.processing_errors import ProcessingError
from app.services.storage import PREVIEWS, StorageBackend, StorageObjectNotFoundError

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
_PREVIEW_MAX_DPI = 150


@dataclass(frozen=True)
class ProcessorConfig:
    max_pages: int = 50
    max_image_pixels: int = 40_000_000
    pdf_min_text_chars: int = 25
    ocr_render_dpi: int = 300
    preview_max_width: int = 1200
    pdf_steps: tuple[str, ...] = ("grayscale", "deskew")
    image_steps: tuple[str, ...] = ("resize", "grayscale", "denoise", "contrast", "deskew", "threshold")


@dataclass
class PageResult:
    page_number: int
    text: str
    text_source: TextSource
    ocr_confidence: float | None
    preview_png: bytes
    width: int  # of the preview image, px
    height: int


@dataclass
class _Run:
    job_id: uuid.UUID
    document_id: uuid.UUID
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


def preview_key(document_id: uuid.UUID, page_number: int) -> str:
    return f"{PREVIEWS}/{document_id}/page-{page_number}.png"


def _usable_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _to_preview(image: Image.Image, max_width: int) -> tuple[bytes, int, int]:
    preview = image.copy()
    if preview.width > max_width:
        preview.thumbnail((max_width, max_width * 10), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    preview.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), preview.width, preview.height


class DocumentProcessor:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: StorageBackend,
        ocr: OCRService,
        config: ProcessorConfig,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.ocr = ocr
        self.config = config
        self._pdf_preprocessor = Preprocessor(config.pdf_steps)
        self._image_preprocessor = Preprocessor(config.image_steps)

    # --- Entry point (runs in the background) ---

    def run(self, job_id: uuid.UUID) -> None:
        with self.session_factory() as db:
            job = db.get(ProcessingJob, job_id)
            if job is None or job.status != JobStatus.QUEUED:
                logger.warning("processing_job_skipped", extra={"job_id": str(job_id)})
                return
            document = db.get(Document, job.document_id)
            run = _Run(job_id=job.id, document_id=document.id)
            job.status = JobStatus.RUNNING
            job.started_at = utcnow()
            self._set_stage(db, job, document, DocumentStatus.PROCESSING)
            logger.info(
                "processing_started", extra={"document_id": str(run.document_id), "attempt": job.attempt}
            )

            try:
                pages = self._extract(db, job, document)
                self._complete(db, run, pages)
            except ProcessingError as exc:
                self._fail(db, run, exc.code, exc.user_message, exc.detail)
            except Exception as exc:
                logger.exception("processing_crashed", extra={"document_id": str(run.document_id)})
                self._fail(
                    db,
                    run,
                    "internal_error",
                    "Processing failed due to an unexpected error.",
                    type(exc).__name__,
                )

    # --- Stages ---

    def _set_stage(self, db: Session, job: ProcessingJob, document: Document, stage: DocumentStatus) -> None:
        document.status = stage
        document.error_message = None
        job.stage = stage
        db.commit()

    def _read_original(self, document: Document) -> bytes:
        try:
            with self.storage.open(document.storage_key) as handle:
                return handle.read()
        except StorageObjectNotFoundError as exc:
            raise ProcessingError("file_missing", "The original file is missing; upload it again.") from exc

    def _extract(self, db: Session, job: ProcessingJob, document: Document) -> list[PageResult]:
        content = self._read_original(document)
        if document.mime_type == PDF_MIME:
            pages = self._extract_pdf(db, job, document, content)
        elif document.mime_type in ("image/png", "image/jpeg"):
            pages = self._extract_image(db, job, document, content)
        else:  # validated at upload; guards against rows created some other way
            raise ProcessingError("unsupported_file_type", "This file type cannot be processed.")

        if not any(_usable_chars(p.text) for p in pages):
            raise ProcessingError("no_text_found", "No readable text was found in this document.")
        return pages

    def _extract_pdf(
        self, db: Session, job: ProcessingJob, document: Document, content: bytes
    ) -> list[PageResult]:
        cfg = self.config
        with PdfDocument(content, max_pages=cfg.max_pages) as pdf:
            texts = [pdf.text(i) for i in range(pdf.page_count)]
            needs_ocr = [_usable_chars(t) < cfg.pdf_min_text_chars for t in texts]
            if any(needs_ocr):
                self._set_stage(db, job, document, DocumentStatus.OCR)

            results = []
            for index, text in enumerate(texts):
                page_number = index + 1
                if needs_ocr[index]:
                    image = pdf.render(index, dpi=cfg.ocr_render_dpi, max_pixels=cfg.max_image_pixels)
                    ocr = self._ocr(self._pdf_preprocessor.run(image), page_number)
                    text, source, confidence = ocr.text, TextSource.OCR, ocr.confidence
                else:
                    image = pdf.render(index, dpi=_PREVIEW_MAX_DPI, max_pixels=cfg.max_image_pixels)
                    source, confidence = TextSource.EMBEDDED, None
                png, width, height = _to_preview(image, cfg.preview_max_width)
                results.append(PageResult(page_number, text.strip(), source, confidence, png, width, height))
            return results

    def _extract_image(
        self, db: Session, job: ProcessingJob, document: Document, content: bytes
    ) -> list[PageResult]:
        image = load_image(content, max_pixels=self.config.max_image_pixels)
        self._set_stage(db, job, document, DocumentStatus.OCR)
        ocr = self._ocr(self._image_preprocessor.run(image), 1)
        png, width, height = _to_preview(image, self.config.preview_max_width)
        return [PageResult(1, ocr.text.strip(), TextSource.OCR, ocr.confidence, png, width, height)]

    def _ocr(self, image: np.ndarray, page_number: int) -> OCRResult:
        try:
            return self.ocr.extract_text(image, page_number=page_number)
        except OCRUnavailableError as exc:
            raise ProcessingError(
                "ocr_unavailable", "Text recognition (OCR) is not available on the server.", detail=str(exc)
            ) from exc
        except OCRError as exc:
            raise ProcessingError(
                "ocr_failed", f"Text recognition failed on page {page_number}.", detail=str(exc)
            ) from exc

    # --- Outcomes ---

    def _existing_preview_keys(self, db: Session, document_id: uuid.UUID) -> set[str]:
        rows = db.scalars(select(DocumentPage.preview_key).where(DocumentPage.document_id == document_id))
        return {key for key in rows if key}

    def _complete(self, db: Session, run: _Run, pages: list[PageResult]) -> None:
        document = db.get(Document, run.document_id, populate_existing=True)
        job = db.get(ProcessingJob, run.job_id, populate_existing=True)
        if document is None or job is None:  # deleted while we were working
            logger.info("processing_abandoned_document_deleted", extra={"document_id": str(run.document_id)})
            return
        old_keys = self._existing_preview_keys(db, run.document_id)
        new_keys = set()
        for page in pages:
            key = preview_key(run.document_id, page.page_number)
            self.storage.save(key, io.BytesIO(page.preview_png))
            new_keys.add(key)

        db.execute(delete(DocumentPage).where(DocumentPage.document_id == run.document_id))
        db.add_all(
            DocumentPage(
                document_id=run.document_id,
                page_number=page.page_number,
                text=page.text,
                text_source=page.text_source,
                ocr_confidence=page.ocr_confidence,
                width=page.width,
                height=page.height,
                preview_key=preview_key(run.document_id, page.page_number),
            )
            for page in pages
        )
        now = utcnow()
        document.page_count = len(pages)
        document.status = DocumentStatus.COMPLETED
        document.error_message = None
        document.processed_at = now
        job.status = JobStatus.SUCCEEDED
        job.stage = DocumentStatus.COMPLETED
        job.finished_at = now
        job.duration_ms = run.elapsed_ms()
        db.commit()

        self._delete_previews(old_keys - new_keys, run.document_id)
        logger.info(
            "processing_completed",
            extra={
                "document_id": str(run.document_id),
                "pages": len(pages),
                "ocr_pages": sum(p.text_source == TextSource.OCR for p in pages),
                "duration_ms": job.duration_ms,
            },
        )

    def _fail(self, db: Session, run: _Run, code: str, user_message: str, detail: str | None) -> None:
        try:
            db.rollback()
            old_keys = self._existing_preview_keys(db, run.document_id)
            db.execute(delete(DocumentPage).where(DocumentPage.document_id == run.document_id))
            document = db.get(Document, run.document_id)
            job = db.get(ProcessingJob, run.job_id)
            if document is None or job is None:  # deleted while we were working
                return
            now = utcnow()
            document.status = DocumentStatus.FAILED
            document.error_message = user_message
            document.page_count = None
            document.processed_at = now
            job.status = JobStatus.FAILED
            job.error_code = code
            job.error_detail = (detail or "")[:500] or None
            job.finished_at = now
            job.duration_ms = run.elapsed_ms()
            db.commit()
        except Exception:
            # The job stays RUNNING; stale-job detection lets it be retried later.
            logger.exception("processing_fail_state_not_saved", extra={"document_id": str(run.document_id)})
            return
        self._delete_previews(old_keys, run.document_id)
        logger.warning(
            "processing_failed",
            extra={"document_id": str(run.document_id), "error_code": code, "duration_ms": job.duration_ms},
        )

    def _delete_previews(self, keys: set[str], document_id: uuid.UUID) -> None:
        for key in keys:
            try:
                self.storage.delete(key)
            except Exception:
                logger.exception("preview_delete_failed", extra={"document_id": str(document_id)})
