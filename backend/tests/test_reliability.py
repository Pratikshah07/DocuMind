"""Duplicate uploads, interrupted-job recovery, orphan cleanup, retryable error codes."""

import io
import os
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import utcnow
from app.models import Document, DocumentPage, DocumentStatus, ExtractedField, JobStatus, ProcessingJob
from app.services.maintenance_service import recover_interrupted_jobs, sweep_orphans
from app.services.storage import DatabaseStorage, LocalStorage
from tests import invoice_texts as T
from tests.samples import corrupt_pdf, make_text_pdf

OTHER = {"X-Workspace-Token": "b" * 40}


def _upload(client: TestClient, content: bytes, *, headers=None, params=None):
    return client.post(
        "/api/documents/upload",
        files={"file": ("invoice.pdf", content, "application/pdf")},
        headers=headers or {},
        params=params or {},
    )


# --- Duplicates ------------------------------------------------------------------


def test_duplicate_upload_is_rejected_with_the_existing_document(client: TestClient) -> None:
    content = make_text_pdf(T.STANDARD_INVOICE)
    first = _upload(client, content).json()

    response = _upload(client, content)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate_document"
    assert error["details"] == {"existing_document_id": first["id"], "existing_filename": "invoice.pdf"}
    assert client.get("/api/documents").json()["total"] == 1  # nothing stored


def test_duplicate_can_be_kept_explicitly(client: TestClient) -> None:
    content = make_text_pdf(T.STANDARD_INVOICE)
    _upload(client, content)
    assert _upload(client, content, params={"allow_duplicate": "true"}).status_code == 202
    assert client.get("/api/documents").json()["total"] == 2


def test_duplicate_check_never_looks_at_other_workspaces(client: TestClient) -> None:
    content = make_text_pdf(T.STANDARD_INVOICE)
    _upload(client, content)
    # Same bytes from another visitor: accepted, and nothing about the first upload is revealed.
    assert _upload(client, content, headers=OTHER).status_code == 202


# --- Interrupted jobs ------------------------------------------------------------------


def _stuck_document(db: Session, *, job_age: timedelta, status=DocumentStatus.OCR) -> Document:
    document = Document(
        original_filename="x.pdf",
        storage_key=f"originals/{uuid.uuid4()}.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="0" * 64,
        status=status,
    )
    db.add(document)
    db.flush()
    db.add(DocumentPage(document_id=document.id, page_number=1, text="old"))
    db.add(ExtractedField(document_id=document.id, name="total", value="1.00"))
    then = utcnow() - job_age
    db.add(
        ProcessingJob(
            document_id=document.id, status=JobStatus.RUNNING, created_at=then, updated_at=then, attempt=1
        )
    )
    db.commit()
    return document


def test_startup_recovery_fails_every_active_job(
    db_session: Session, session_factory: sessionmaker, storage: LocalStorage
) -> None:
    document = _stuck_document(db_session, job_age=timedelta(seconds=5))

    assert recover_interrupted_jobs(session_factory, storage, older_than=None) == 1

    db_session.expire_all()
    document = db_session.get(Document, document.id)
    assert document.status == DocumentStatus.FAILED
    assert "interrupted" in document.error_message
    assert document.pages == [] and document.fields == []  # no stale results on a FAILED document
    job = document.jobs[0]
    assert job.status == JobStatus.FAILED and job.error_code == "interrupted"


def test_periodic_recovery_leaves_recent_jobs_alone(
    db_session: Session, session_factory: sessionmaker, storage: LocalStorage
) -> None:
    recent = _stuck_document(db_session, job_age=timedelta(minutes=1))
    stale = _stuck_document(db_session, job_age=timedelta(hours=1))

    assert recover_interrupted_jobs(session_factory, storage, older_than=timedelta(minutes=15)) == 1

    db_session.expire_all()
    assert db_session.get(Document, recent.id).status == DocumentStatus.OCR
    assert db_session.get(Document, stale.id).status == DocumentStatus.FAILED


def test_uploaded_document_without_a_job_is_recovered(
    db_session: Session, session_factory: sessionmaker, storage: LocalStorage
) -> None:
    document = Document(
        original_filename="x.pdf",
        storage_key="originals/never-queued.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="1" * 64,
        status=DocumentStatus.UPLOADED,
    )
    db_session.add(document)
    db_session.commit()

    recover_interrupted_jobs(session_factory, storage, older_than=None)

    db_session.expire_all()
    assert db_session.get(Document, document.id).status == DocumentStatus.FAILED


def test_interrupted_document_can_be_retried(
    client: TestClient, db_session: Session, session_factory: sessionmaker, storage: LocalStorage
) -> None:
    document_id = _upload(client, make_text_pdf(T.STANDARD_INVOICE)).json()["id"]
    job = db_session.query(ProcessingJob).filter_by(document_id=uuid.UUID(document_id)).one()
    job.status = JobStatus.RUNNING  # pretend the server died mid-run
    db_session.get(Document, uuid.UUID(document_id)).status = DocumentStatus.OCR
    db_session.commit()

    recover_interrupted_jobs(session_factory, storage, older_than=None)
    db_session.expire_all()  # the API shares this session; recovery used its own
    status = client.get(f"/api/documents/{document_id}/status").json()
    assert status["status"] == "FAILED" and status["job"]["retryable"] is True

    assert client.post(f"/api/documents/{document_id}/process").status_code == 202
    assert client.get(f"/api/documents/{document_id}/status").json()["status"] == "COMPLETED"


def test_permanent_failures_are_not_retryable(client: TestClient) -> None:
    response = client.post(
        "/api/documents/upload", files={"file": ("bad.pdf", corrupt_pdf(), "application/pdf")}
    )
    document_id = response.json()["id"]
    job = client.get(f"/api/documents/{document_id}/status").json()["job"]
    assert job["error_code"] == "corrupt_pdf" and job["retryable"] is False


# --- Orphaned storage objects ----------------------------------------------------------


def _age(storage: LocalStorage, key: str, hours: float) -> None:
    path = storage.root / key
    old = (utcnow() - timedelta(hours=hours)).timestamp()
    os.utime(path, (old, old))


def test_orphan_sweep_removes_only_old_unreferenced_files(
    client: TestClient, db_session: Session, session_factory: sessionmaker, storage: LocalStorage
) -> None:
    document_id = _upload(client, make_text_pdf(T.STANDARD_INVOICE)).json()["id"]
    document = db_session.get(Document, uuid.UUID(document_id))
    referenced = [document.storage_key] + [p.preview_key for p in document.pages]
    storage.save("originals/orphan-old.pdf", io.BytesIO(b"x"))
    storage.save("previews/gone/page-1.png", io.BytesIO(b"x"))
    storage.save("originals/orphan-new.pdf", io.BytesIO(b"x"))  # maybe an upload in flight
    tmp = storage.root / "originals" / ".upload-abc.tmp"
    tmp.write_bytes(b"partial")
    for key in referenced + ["originals/orphan-old.pdf", "previews/gone/page-1.png"]:
        _age(storage, key, hours=5)
    old = (utcnow() - timedelta(hours=5)).timestamp()
    os.utime(tmp, (old, old))

    removed = sweep_orphans(session_factory, storage, grace=timedelta(hours=1))

    assert removed == 3
    assert all(storage.exists(k) for k in referenced)
    assert storage.exists("originals/orphan-new.pdf")
    assert not storage.exists("originals/orphan-old.pdf") and not tmp.exists()


def test_database_storage_lists_objects(session_factory: sessionmaker) -> None:
    storage = DatabaseStorage(session_factory)
    storage.save("originals/a.pdf", io.BytesIO(b"abc"))
    listed = dict(storage.list_objects())
    assert set(listed) == {"originals/a.pdf"} and listed["originals/a.pdf"].tzinfo is not None
    # Fresh object: inside any grace period, so the sweep keeps it.
    assert sweep_orphans(session_factory, storage, grace=timedelta(hours=1)) == 0
    assert storage.exists("originals/a.pdf")
