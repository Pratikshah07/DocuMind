"""Extraction inside the processing pipeline: stages, persistence, idempotent reprocessing."""

import io
import logging
import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Document,
    DocumentStatus,
    DocumentType,
    ExtractedField,
    JobStatus,
    LineItem,
    ProcessingJob,
    ValidationWarning,
)
from app.services.extraction.types import FIELD_NAMES
from app.services.ocr import OCRError, TesseractOCR
from app.services.pipeline import DocumentProcessor, ProcessorConfig
from app.services.storage import LocalStorage
from tests import invoice_texts as T
from tests.conftest import FakeOCR, requires_tesseract
from tests.samples import make_png, make_scanned_text_pdf, make_text_pdf


@pytest.fixture
def processor(
    session_factory: sessionmaker[Session], storage: LocalStorage, fake_ocr: FakeOCR
) -> DocumentProcessor:
    return DocumentProcessor(session_factory, storage, fake_ocr, ProcessorConfig())


@pytest.fixture
def queue(db_session: Session, storage: LocalStorage):
    """Store a file + document row + QUEUED job (as upload does). Returns (document_id, job_id)."""

    def _queue(content: bytes, mime: str = "application/pdf", document_id: uuid.UUID | None = None):
        if document_id is None:
            document_id = uuid.uuid4()
            key = f"originals/{document_id}{'.pdf' if mime == 'application/pdf' else '.png'}"
            storage.save(key, io.BytesIO(content))
            db_session.add(
                Document(
                    id=document_id,
                    original_filename="sample",
                    storage_key=key,
                    mime_type=mime,
                    size_bytes=len(content),
                    sha256="0" * 64,
                )
            )
        attempt = (
            db_session.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.document_id == document_id)
            )
            or 0
        ) + 1
        job = ProcessingJob(document_id=document_id, status=JobStatus.QUEUED, attempt=attempt)
        db_session.add(job)
        db_session.commit()
        return document_id, job.id

    return _queue


def counts(db: Session, document_id: uuid.UUID) -> dict[str, int]:
    return {
        model.__tablename__: db.scalar(
            select(func.count()).select_from(model).where(model.document_id == document_id)
        )
        for model in (ExtractedField, LineItem, ValidationWarning)
    }


def reload(db: Session, document_id: uuid.UUID) -> Document:
    db.expire_all()
    return db.get(Document, document_id)


def test_complete_invoice_is_persisted(processor, queue, db_session) -> None:
    document_id, job_id = queue(make_text_pdf(T.STANDARD_INVOICE))

    processor.run(job_id)

    document = reload(db_session, document_id)
    assert document.status == DocumentStatus.COMPLETED
    assert db_session.get(ProcessingJob, job_id).stage == DocumentStatus.COMPLETED
    # Headline columns hold the validated, typed values.
    assert (document.document_type, document.vendor_name, document.invoice_number) == (
        DocumentType.INVOICE,
        "Northstar Studio LLC",
        "NS-1048",
    )
    assert (document.invoice_date, document.due_date) == (date(2025, 3, 18), date(2025, 4, 17))
    assert (document.subtotal, document.tax, document.total, document.currency) == (
        D("4500.00"),
        D("320.00"),
        D("4820.00"),
        "USD",
    )
    assert document.payment_method == "Visa" and 0.8 < document.overall_confidence <= 1

    rows = {f.name: f for f in document.fields}
    assert set(rows) == set(FIELD_NAMES) | {"document_type"}  # missing fields are explicit rows
    assert rows["due_date"].value == "17/04/2025" and rows["due_date"].normalized_value == "2025-04-17"
    assert rows["total"].normalized_value == "4820.00" and rows["total"].page_number == 1
    assert rows["shipping_address"].value is None and rows["shipping_address"].confidence is None
    assert rows["document_type"].method == "rule"
    assert [(i.position, i.description, i.total) for i in document.line_items] == [
        (1, "Brand identity refinement", D("2800.00")),
        (2, "Web design consultation", D("1700.00")),
    ]
    assert document.warnings == []


def test_extraction_stages_are_observable(processor, queue, db_session, session_factory, fake_ocr) -> None:
    # A scanned page so the fake OCR runs; its text is an invoice. Observe status as another reader would.
    fake_ocr.text = T.TOTALS_MISMATCH
    document_id, job_id = queue(make_png(), mime="image/png")
    seen = []
    original_set_stage = processor._set_stage

    def spy(db, job, document, stage):
        original_set_stage(db, job, document, stage)
        with session_factory() as other:
            seen.append(other.get(Document, document_id).status)

    processor._set_stage = spy  # type: ignore[method-assign]
    processor.run(job_id)

    assert seen == [
        DocumentStatus.PROCESSING,
        DocumentStatus.OCR,
        DocumentStatus.EXTRACTING,
        DocumentStatus.VALIDATING,
    ]
    document = reload(db_session, document_id)
    assert document.status == DocumentStatus.NEEDS_REVIEW
    assert [w.code for w in document.warnings] == ["totals_mismatch"]


def test_invalid_values_are_not_copied_to_headline_columns(processor, queue, db_session) -> None:
    document_id, job_id = queue(make_text_pdf(T.MALFORMED))

    processor.run(job_id)

    document = reload(db_session, document_id)
    assert document.status == DocumentStatus.NEEDS_REVIEW
    assert document.invoice_date is None  # invalid → column stays NULL ...
    row = next(f for f in document.fields if f.name == "invoice_date")
    assert row.value == "31/02/2025" and row.normalized_value is None  # ... raw text kept on the field row
    assert {(w.field, w.code) for w in document.warnings} == {
        ("invoice_date", "invalid_format"),
        ("total", "missing_required_field"),
    }


def test_reprocessing_is_idempotent(processor, queue, db_session) -> None:
    document_id, first = queue(make_text_pdf(*T.MULTI_PAGE))
    processor.run(first)
    before = counts(db_session, document_id)
    snapshot = {
        f.name: (f.value, f.normalized_value, f.confidence) for f in reload(db_session, document_id).fields
    }

    _, second = queue(b"", document_id=document_id)
    processor.run(second)

    assert (
        counts(db_session, document_id)
        == before
        == {"extracted_fields": 16, "line_items": 5, "validation_warnings": 0}
    )
    document = reload(db_session, document_id)
    assert {f.name: (f.value, f.normalized_value, f.confidence) for f in document.fields} == snapshot
    assert [i.position for i in document.line_items] == [1, 2, 3, 4, 5]


def test_failure_after_success_clears_extraction(processor, queue, db_session, fake_ocr) -> None:
    fake_ocr.text = T.RECEIPT
    document_id, first = queue(make_png(), mime="image/png")
    processor.run(first)
    assert reload(db_session, document_id).total == D("17.86")

    fake_ocr.error = OCRError("engine crashed")
    _, second = queue(b"", document_id=document_id)
    processor.run(second)

    document = reload(db_session, document_id)
    assert document.status == DocumentStatus.FAILED
    assert counts(db_session, document_id) == {
        "extracted_fields": 0,
        "line_items": 0,
        "validation_warnings": 0,
    }
    assert (document.total, document.vendor_name, document.document_type, document.overall_confidence) == (
        None,
        None,
        None,
        None,
    )


def test_extraction_logs_contain_no_values(processor, queue, caplog) -> None:
    _, job_id = queue(make_text_pdf(T.STANDARD_INVOICE))
    with caplog.at_level(logging.DEBUG):
        processor.run(job_id)

    completed = next(r for r in caplog.records if r.getMessage() == "processing_completed")
    assert completed.fields_found == 11 and completed.line_items == 2 and completed.status == "COMPLETED"
    blob = " ".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    for secret in ("Northstar", "NS-1048", "4,820.00", "4820", "Meridian", "Pine Street"):
        assert secret not in blob


@requires_tesseract
def test_scanned_invoice_end_to_end_with_real_ocr(queue, db_session, session_factory, storage) -> None:
    processor = DocumentProcessor(session_factory, storage, TesseractOCR(), ProcessorConfig())
    document_id, job_id = queue(make_scanned_text_pdf(T.STANDARD_INVOICE))

    processor.run(job_id)

    document = reload(db_session, document_id)
    assert document.status in (DocumentStatus.COMPLETED, DocumentStatus.NEEDS_REVIEW)
    assert document.pages[0].text_source.value == "OCR"
    assert (document.invoice_number, document.invoice_date, document.total) == (
        "NS-1048",
        date(2025, 3, 18),
        D("4820.00"),
    )
    assert (document.subtotal, document.tax) == (D("4500.00"), D("320.00"))
    rows = {f.name: f for f in document.fields}
    # OCR'd values carry lower confidence than the same values from a text layer (0.95).
    assert rows["total"].confidence < 0.95
