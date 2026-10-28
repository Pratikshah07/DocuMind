"""Processing endpoints: upload → background processing → status, retries, previews, health."""

import io
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import JobStatus, ProcessingJob
from app.services.ocr import OCRError
from tests.conftest import FakeOCR
from tests.samples import corrupt_pdf, make_mixed_pdf, make_pdf, make_png


def upload(client: TestClient, content: bytes, filename: str, mime: str) -> dict:
    response = client.post("/api/documents/upload", files={"file": (filename, content, mime)})
    assert response.status_code == 202, response.text
    return response.json()


def test_upload_queues_and_processes(client: TestClient) -> None:
    body = upload(client, make_mixed_pdf(), "invoice.pdf", "application/pdf")

    status = client.get(f"/api/documents/{body['id']}/status")

    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "COMPLETED" and data["page_count"] == 2 and data["error_message"] is None
    job = data["job"]
    assert job["id"] == body["job_id"]
    assert job["status"] == "SUCCEEDED" and job["stage"] == "COMPLETED" and job["attempt"] == 1
    assert job["error_code"] is None and job["duration_ms"] >= 0
    assert "error_detail" not in job  # internal detail is never exposed


def test_detail_includes_page_text_and_previews(client: TestClient) -> None:
    document_id = upload(client, make_mixed_pdf(), "invoice.pdf", "application/pdf")["id"]

    pages = client.get(f"/api/documents/{document_id}").json()["pages"]

    assert [(p["page_number"], p["text_source"], p["has_preview"]) for p in pages] == [
        (1, "EMBEDDED", True),
        (2, "OCR", True),
    ]
    assert "INV-2041" in pages[0]["text"] and pages[1]["text"] == "FAKE OCR TEXT 123"
    assert pages[1]["ocr_confidence"] == 0.91


def test_page_preview_is_a_png(client: TestClient) -> None:
    document_id = upload(client, make_pdf(), "invoice.pdf", "application/pdf")["id"]

    response = client.get(f"/api/documents/{document_id}/pages/1/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG" and image.width <= 1200

    for bad in (
        f"/api/documents/{document_id}/pages/2/preview",
        f"/api/documents/{uuid.uuid4()}/pages/1/preview",
    ):
        assert client.get(bad).status_code == 404
    missing = client.get(f"/api/documents/{document_id}/pages/2/preview").json()
    assert missing["error"]["code"] == "preview_not_found"


def test_failed_processing_is_reported_safely(client: TestClient) -> None:
    document_id = upload(client, corrupt_pdf(), "broken.pdf", "application/pdf")["id"]

    data = client.get(f"/api/documents/{document_id}/status").json()

    assert data["status"] == "FAILED"
    assert data["error_message"] == "The PDF file is damaged and could not be read."
    assert data["job"]["status"] == "FAILED" and data["job"]["error_code"] == "corrupt_pdf"
    assert data["page_count"] is None


def test_retry_after_failure(client: TestClient, fake_ocr: FakeOCR) -> None:
    fake_ocr.error = OCRError("engine crashed")
    document_id = upload(client, make_png(), "receipt.png", "image/png")["id"]
    assert client.get(f"/api/documents/{document_id}/status").json()["status"] == "FAILED"

    fake_ocr.error = None
    response = client.post(f"/api/documents/{document_id}/process")

    assert response.status_code == 202
    assert response.json()["job"]["attempt"] == 2
    data = client.get(f"/api/documents/{document_id}/status").json()
    assert data["status"] in ("COMPLETED", "NEEDS_REVIEW")  # fake-OCR text has no invoice fields
    assert data["job"]["attempt"] == 2 and data["error_message"] is None


def test_reprocess_completed_document_keeps_one_set_of_pages(client: TestClient) -> None:
    document_id = upload(client, make_mixed_pdf(), "invoice.pdf", "application/pdf")["id"]

    assert client.post(f"/api/documents/{document_id}/process").status_code == 202

    detail = client.get(f"/api/documents/{document_id}").json()
    assert [p["page_number"] for p in detail["pages"]] == [1, 2]
    assert client.get(f"/api/documents/{document_id}/status").json()["job"]["attempt"] == 2


def test_cannot_queue_while_a_job_is_active(client: TestClient, db_session: Session) -> None:
    document_id = upload(client, make_pdf(), "invoice.pdf", "application/pdf")["id"]
    db_session.add(ProcessingJob(document_id=uuid.UUID(document_id), status=JobStatus.RUNNING, attempt=2))
    db_session.commit()

    response = client.post(f"/api/documents/{document_id}/process")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_processing"


def test_stale_active_job_does_not_block_a_retry(client: TestClient, db_session: Session) -> None:
    document_id = uuid.UUID(upload(client, make_pdf(), "invoice.pdf", "application/pdf")["id"])
    stuck = ProcessingJob(document_id=document_id, status=JobStatus.RUNNING, attempt=2)
    db_session.add(stuck)
    db_session.commit()
    stuck.updated_at = utcnow() - timedelta(hours=1)  # e.g. the server restarted mid-run
    db_session.commit()

    response = client.post(f"/api/documents/{document_id}/process")

    assert response.status_code == 202
    db_session.expire_all()
    assert db_session.get(ProcessingJob, stuck.id).error_code == "stale_job"
    assert client.get(f"/api/documents/{document_id}/status").json()["job"]["attempt"] == 3


def test_unknown_document(client: TestClient) -> None:
    for method, path in (("post", "process"), ("get", "status")):
        response = getattr(client, method)(f"/api/documents/{uuid.uuid4()}/{path}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "document_not_found"


def test_health_reports_ocr_component(client: TestClient, fake_ocr: FakeOCR) -> None:
    assert client.get("/api/health").json()["components"]["ocr"] == {"status": "ok", "detail": None}

    fake_ocr.available = False
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["components"]["ocr"]["status"] == "error"
