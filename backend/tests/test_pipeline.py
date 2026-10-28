"""DocumentProcessor: stages, outcomes, retries and consistency (fake OCR unless noted)."""

import io
import logging
import uuid

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Document, DocumentPage, DocumentStatus, JobStatus, ProcessingJob, TextSource
from app.services.ocr import OCRError, OCRUnavailableError, TesseractOCR
from app.services.pipeline import DocumentProcessor, ProcessorConfig, preview_key
from app.services.storage import LocalStorage
from tests.conftest import FakeOCR, requires_tesseract
from tests.samples import (
    corrupt_pdf,
    make_blank_png,
    make_encrypted_pdf,
    make_mixed_pdf,
    make_pdf,
    make_photo_jpeg,
    make_png,
    make_scanned_pdf,
    truncate,
)

PDF, PNG, JPEG = "application/pdf", "image/png", "image/jpeg"
# Finished successfully. Fake-OCR text has no invoice fields, so extraction sends it to review;
# these tests are about OCR/retries, extraction outcomes are covered in test_extraction_pipeline.py.
PROCESSED = (DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW)


@pytest.fixture
def make_doc(db_session: Session, storage: LocalStorage):
    """Store bytes and create a document row plus a QUEUED job, as the upload endpoint would."""

    def _make(content: bytes, mime: str) -> tuple[uuid.UUID, uuid.UUID]:
        document_id = uuid.uuid4()
        ext = {PDF: ".pdf", PNG: ".png", JPEG: ".jpg"}[mime]
        key = f"originals/{document_id}{ext}"
        storage.save(key, io.BytesIO(content))
        db_session.add(
            Document(
                id=document_id,
                original_filename=f"sample{ext}",
                storage_key=key,
                mime_type=mime,
                size_bytes=len(content),
                sha256="0" * 64,
            )
        )
        job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED, attempt=1)
        db_session.add(job)
        db_session.commit()
        return document_id, job.id

    return _make


def queue_again(db: Session, document_id: uuid.UUID) -> uuid.UUID:
    attempts = db.scalar(
        select(func.count()).select_from(ProcessingJob).where(ProcessingJob.document_id == document_id)
    )
    job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED, attempt=attempts + 1)
    db.add(job)
    db.commit()
    return job.id


@pytest.fixture
def processor(
    session_factory: sessionmaker[Session], storage: LocalStorage, fake_ocr: FakeOCR
) -> DocumentProcessor:
    return DocumentProcessor(session_factory, storage, fake_ocr, ProcessorConfig())


def state(
    db: Session, document_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Document, ProcessingJob, list[DocumentPage]]:
    db.expire_all()
    pages = db.scalars(
        select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)
    ).all()
    return db.get(Document, document_id), db.get(ProcessingJob, job_id), list(pages)


def preview_files(storage: LocalStorage, document_id: uuid.UUID) -> list[str]:
    folder = storage.root / "previews" / str(document_id)
    return sorted(p.name for p in folder.glob("*.png")) if folder.exists() else []


# --- Successful runs --------------------------------------------------------


def test_text_pdf_uses_embedded_text_without_ocr(make_doc, processor, fake_ocr, db_session, storage) -> None:
    document_id, job_id = make_doc(make_pdf(), PDF)

    processor.run(job_id)

    document, job, pages = state(db_session, document_id, job_id)
    assert document.status == DocumentStatus.COMPLETED
    assert document.page_count == 1 and document.processed_at is not None and document.error_message is None
    assert job.status == JobStatus.SUCCEEDED and job.stage == DocumentStatus.COMPLETED
    assert job.started_at is not None and job.finished_at is not None and job.duration_ms >= 0
    assert fake_ocr.calls == []
    [page] = pages
    assert page.text_source == TextSource.EMBEDDED and page.ocr_confidence is None
    assert "INV-2041" in page.text
    assert page.preview_key == preview_key(document_id, 1)
    with storage.open(page.preview_key) as handle:
        preview = Image.open(handle)
        assert preview.format == "PNG" and preview.size == (page.width, page.height)


def test_scanned_pdf_goes_through_ocr_stage(
    make_doc, processor, fake_ocr, db_session, session_factory
) -> None:
    document_id, job_id = make_doc(make_scanned_pdf(), PDF)
    seen: list[DocumentStatus] = []

    def observe(_page: int) -> None:  # status as another reader sees it while OCR runs
        with session_factory() as other:
            seen.append(other.get(Document, document_id).status)

    fake_ocr.on_call = observe
    processor.run(job_id)

    document, job, [page] = state(db_session, document_id, job_id)
    assert seen == [DocumentStatus.OCR]
    assert document.status in PROCESSED
    assert page.text_source == TextSource.OCR
    assert page.text == "FAKE OCR TEXT 123" and page.ocr_confidence == pytest.approx(0.91)
    [(page_number, shape)] = fake_ocr.calls
    assert page_number == 1
    assert len(shape) == 2 and shape[1] == 2550  # grayscale (pdf profile), rendered at 300 dpi (8.5 in)


def test_mixed_pdf_ocrs_only_the_scanned_page(make_doc, processor, fake_ocr, db_session) -> None:
    document_id, job_id = make_doc(make_mixed_pdf(), PDF)

    processor.run(job_id)

    document, _, pages = state(db_session, document_id, job_id)
    assert document.page_count == 2
    assert [p.text_source for p in pages] == [TextSource.EMBEDDED, TextSource.OCR]
    assert [call[0] for call in fake_ocr.calls] == [2]


def test_multi_page_pdf_keeps_page_numbers(make_doc, processor, db_session, storage) -> None:
    pages_text = (["First page with plenty of text"], ["Second page with plenty of text"], ["Short"])
    document_id, job_id = make_doc(make_pdf(*pages_text), PDF)  # page 3 is under 25 chars → OCR'd

    processor.run(job_id)

    _, _, pages = state(db_session, document_id, job_id)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert pages[0].text == "First page with plenty of text"
    assert [p.text_source for p in pages] == [TextSource.EMBEDDED, TextSource.EMBEDDED, TextSource.OCR]
    assert preview_files(storage, document_id) == ["page-1.png", "page-2.png", "page-3.png"]


def test_image_uses_image_preprocessing_profile(make_doc, processor, fake_ocr, db_session) -> None:
    document_id, job_id = make_doc(make_png(), PNG)

    processor.run(job_id)

    document, _, [page] = state(db_session, document_id, job_id)
    assert document.status in PROCESSED and page.text_source == TextSource.OCR
    [(_, shape)] = fake_ocr.calls
    assert len(shape) == 2  # grayscale after resize/denoise/contrast/deskew


def test_blank_page_inside_document_does_not_fail_it(make_doc, processor, fake_ocr, db_session) -> None:
    document_id, job_id = make_doc(make_scanned_pdf(["Real content on page one"], None), PDF)
    fake_ocr.on_call = lambda page: setattr(fake_ocr, "text", "" if page == 2 else "Real content")

    processor.run(job_id)

    document, _, pages = state(db_session, document_id, job_id)
    assert document.status in PROCESSED
    assert [p.text for p in pages] == ["Real content", ""]


# --- Failures ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "mime", "code"),
    [
        (corrupt_pdf(), PDF, "corrupt_pdf"),
        (truncate(make_pdf(), 0.1), PDF, "corrupt_pdf"),
        (make_encrypted_pdf(), PDF, "encrypted_pdf"),
        (truncate(make_png(), 0.5), PNG, "corrupt_image"),
        (b"\xff\xd8\xff\xe0not really a jpeg", JPEG, "corrupt_image"),
    ],
    ids=["garbage-pdf", "truncated-pdf", "encrypted-pdf", "truncated-png", "fake-jpeg"],
)
def test_unreadable_files_fail_cleanly(make_doc, processor, db_session, storage, content, mime, code) -> None:
    document_id, job_id = make_doc(content, mime)

    processor.run(job_id)

    document, job, pages = state(db_session, document_id, job_id)
    assert document.status == DocumentStatus.FAILED
    assert job.status == JobStatus.FAILED and job.error_code == code
    assert document.error_message and "Traceback" not in document.error_message
    assert pages == [] and document.page_count is None
    assert preview_files(storage, document_id) == []


def test_document_with_no_text_fails(make_doc, processor, fake_ocr, db_session) -> None:
    fake_ocr.text = "   "
    document_id, job_id = make_doc(make_blank_png(), PNG)

    processor.run(job_id)

    document, job, _ = state(db_session, document_id, job_id)
    assert (document.status, job.error_code) == (DocumentStatus.FAILED, "no_text_found")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (OCRUnavailableError("missing"), "ocr_unavailable"),
        (OCRError("Tesseract timed out after 60s"), "ocr_failed"),
    ],
)
def test_ocr_errors_fail_the_document(make_doc, processor, fake_ocr, db_session, error, code) -> None:
    fake_ocr.error = error
    document_id, job_id = make_doc(make_scanned_pdf(), PDF)

    processor.run(job_id)

    document, job, _ = state(db_session, document_id, job_id)
    assert (document.status, job.error_code) == (DocumentStatus.FAILED, code)
    assert job.stage == DocumentStatus.OCR  # the stage it failed in
    assert job.error_detail == str(error)  # internal detail kept on the job only


def test_unexpected_exception_is_contained(make_doc, processor, fake_ocr, db_session) -> None:
    fake_ocr.error = ValueError("secret internal state 0xdeadbeef")
    document_id, job_id = make_doc(make_png(), PNG)

    processor.run(job_id)  # must not raise

    document, job, _ = state(db_session, document_id, job_id)
    assert job.error_code == "internal_error" and job.error_detail == "ValueError"
    assert document.error_message == "Processing failed due to an unexpected error."


def test_missing_original_file(make_doc, processor, db_session, storage) -> None:
    document_id, job_id = make_doc(make_pdf(), PDF)
    storage.delete(db_session.get(Document, document_id).storage_key)

    processor.run(job_id)

    _, job, _ = state(db_session, document_id, job_id)
    assert job.error_code == "file_missing"


def test_page_limit_from_config(make_doc, session_factory, storage, fake_ocr, db_session) -> None:
    processor = DocumentProcessor(session_factory, storage, fake_ocr, ProcessorConfig(max_pages=2))
    document_id, job_id = make_doc(make_pdf(["a" * 30], ["b" * 30], ["c" * 30]), PDF)

    processor.run(job_id)

    _, job, _ = state(db_session, document_id, job_id)
    assert job.error_code == "too_many_pages"


# --- Retries and consistency ------------------------------------------------


def test_reprocessing_replaces_pages_instead_of_duplicating(make_doc, processor, db_session, storage) -> None:
    document_id, first = make_doc(make_mixed_pdf(), PDF)
    processor.run(first)
    second = queue_again(db_session, document_id)

    processor.run(second)

    document, job, pages = state(db_session, document_id, second)
    assert [p.page_number for p in pages] == [1, 2]
    assert job.attempt == 2 and job.status == JobStatus.SUCCEEDED
    assert db_session.get(ProcessingJob, first).status == JobStatus.SUCCEEDED  # history kept
    assert preview_files(storage, document_id) == ["page-1.png", "page-2.png"]


def test_retry_after_failure_succeeds(make_doc, processor, fake_ocr, db_session) -> None:
    fake_ocr.error = OCRError("flaky")
    document_id, first = make_doc(make_png(), PNG)
    processor.run(first)
    assert state(db_session, document_id, first)[0].status == DocumentStatus.FAILED

    fake_ocr.error = None
    second = queue_again(db_session, document_id)
    processor.run(second)

    document, _, pages = state(db_session, document_id, second)
    assert document.status in PROCESSED and document.error_message is None
    assert len(pages) == 1


def test_failure_after_success_clears_stale_pages_and_previews(
    make_doc, processor, fake_ocr, db_session, storage
) -> None:
    document_id, first = make_doc(make_png(), PNG)
    processor.run(first)
    assert preview_files(storage, document_id) == ["page-1.png"]

    fake_ocr.error = OCRError("engine crashed")
    second = queue_again(db_session, document_id)
    processor.run(second)

    document, _, pages = state(db_session, document_id, second)
    assert document.status == DocumentStatus.FAILED
    assert pages == [] and preview_files(storage, document_id) == []


def test_job_that_is_not_queued_is_not_run_twice(make_doc, processor, fake_ocr, db_session) -> None:
    document_id, job_id = make_doc(make_png(), PNG)
    processor.run(job_id)
    processor.run(job_id)  # duplicate delivery
    processor.run(uuid.uuid4())  # unknown job

    assert len(fake_ocr.calls) == 1


def test_document_deleted_during_processing(
    make_doc, processor, fake_ocr, db_session, session_factory, storage
):
    document_id, job_id = make_doc(make_png(), PNG)

    def delete_document(_page: int) -> None:
        with session_factory() as other:
            other.delete(other.get(Document, document_id))
            other.commit()

    fake_ocr.on_call = delete_document
    processor.run(job_id)  # must not raise

    assert db_session.get(Document, document_id) is None
    assert preview_files(storage, document_id) == []


def test_logs_never_contain_document_text(make_doc, processor, fake_ocr, caplog) -> None:
    fake_ocr.text = "SENSITIVE-CUSTOMER-NAME"
    _, job_id = make_doc(make_png(), PNG)
    with caplog.at_level(logging.DEBUG):
        processor.run(job_id)

    assert caplog.records, "expected processing logs"
    for record in caplog.records:
        assert "SENSITIVE-CUSTOMER-NAME" not in record.getMessage()
        assert all("SENSITIVE-CUSTOMER-NAME" not in str(v) for v in vars(record).values())


# --- Real OCR end to end -----------------------------------------------------


@requires_tesseract
@pytest.mark.parametrize(
    ("content", "mime"),
    [(make_scanned_pdf(), PDF), (make_png(), PNG), (make_photo_jpeg(), JPEG)],
    ids=["scanned-pdf", "png", "skewed-noisy-photo"],
)
def test_real_tesseract_reads_key_values(
    make_doc, session_factory, storage, db_session, content, mime
) -> None:
    processor = DocumentProcessor(session_factory, storage, TesseractOCR(), ProcessorConfig())
    document_id, job_id = make_doc(content, mime)

    processor.run(job_id)

    document, job, [page] = state(db_session, document_id, job_id)
    assert document.status == DocumentStatus.COMPLETED, job.error_code
    for token in ("NORTHWIND", "INV-2041", "54.00"):
        assert token in page.text, f"{token!r} not found in OCR text"
    assert 0.5 < page.ocr_confidence <= 1.0
