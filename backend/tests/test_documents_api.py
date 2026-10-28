import hashlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.models import (
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentType,
    ExtractedField,
    LineItem,
    ValidationWarning,
)
from app.services.storage import LocalStorage
from tests.samples import make_jpeg, make_pdf, make_png


def upload(client: TestClient, content: bytes, filename: str, mime: str = "application/pdf"):
    return client.post("/api/documents/upload", files={"file": (filename, content, mime)})


def stored_files(storage: LocalStorage) -> list[str]:
    return sorted(p.name for p in (storage.root / "originals").iterdir())


# --- Upload -----------------------------------------------------------------


def test_upload_pdf_persists_row_and_file(client: TestClient, db_session: Session, storage) -> None:
    content = make_pdf()

    response = upload(client, content, "Northwind Invoice 1048.pdf")

    assert response.status_code == 202
    body = response.json()
    assert body["original_filename"] == "Northwind Invoice 1048.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["size_bytes"] == len(content)
    assert body["status"] == "UPLOADED"  # the response is sent before processing starts
    assert "job_id" in body
    assert "storage_key" not in body  # storage layout is never exposed
    assert response.headers["Location"] == f"/api/documents/{body['id']}"

    document = db_session.get(Document, uuid.UUID(body["id"]))
    assert document is not None
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert document.storage_key == f"originals/{document.id}.pdf"
    with storage.open(document.storage_key) as handle:
        assert handle.read() == content


@pytest.mark.parametrize(
    ("content", "filename", "mime", "stored_ext"),
    [
        (make_png(), "receipt.png", "image/png", ".png"),
        (make_jpeg(), "receipt.jpeg", "image/jpeg", ".jpg"),
    ],
)
def test_upload_images(client: TestClient, storage, content, filename, mime, stored_ext) -> None:
    response = upload(client, content, filename, mime)

    assert response.status_code == 202
    assert response.json()["mime_type"] == mime
    assert stored_files(storage) == [f"{response.json()['id']}{stored_ext}"]


def test_upload_sanitizes_traversal_filename(client: TestClient, storage) -> None:
    response = upload(client, make_pdf(), "..\\..\\secrets\\invoice.pdf")

    assert response.status_code == 202
    assert response.json()["original_filename"] == "invoice.pdf"
    assert stored_files(storage) == [f"{response.json()['id']}.pdf"]


@pytest.mark.parametrize(
    ("content", "filename", "mime", "status", "code"),
    [
        (make_pdf(), "invoice.txt", "text/plain", 415, "unsupported_file_type"),
        (b"<html></html>", "invoice.pdf", "application/pdf", 415, "unrecognized_file_content"),
        (make_png(), "invoice.pdf", "application/pdf", 415, "file_type_mismatch"),
        (make_pdf(), "invoice.pdf", "image/png", 415, "file_type_mismatch"),
        (b"", "invoice.pdf", "application/pdf", 422, "empty_file"),
    ],
)
def test_rejected_uploads_store_nothing(
    client: TestClient, db_session: Session, storage, content, filename, mime, status, code
) -> None:
    response = upload(client, content, filename, mime)

    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert stored_files(storage) == []
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0


def test_upload_over_size_limit_returns_413(client: TestClient, settings: Settings, storage) -> None:
    small_limit = settings.model_copy(update={"max_upload_size": 100})
    client.app.dependency_overrides[get_settings] = lambda: small_limit

    response = upload(client, make_pdf(), "invoice.pdf")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert stored_files(storage) == []


def test_upload_without_file_field_is_validation_error(client: TestClient) -> None:
    response = client.post("/api/documents/upload", data={"not_file": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --- List -------------------------------------------------------------------


@pytest.fixture
def seeded(db_session: Session) -> list[Document]:
    """Documents with extraction fields set directly (extraction itself arrives in Phase 4)."""

    def doc(name: str, **fields) -> Document:
        return Document(
            original_filename=name,
            storage_key=f"originals/{uuid.uuid4()}.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="0" * 64,
            **fields,
        )

    docs = [
        doc("a.pdf", vendor_name="Acme 100% Supplies", total=Decimal("50.00"), invoice_date=date(2025, 1, 5),
            status=DocumentStatus.COMPLETED, document_type=DocumentType.INVOICE),
        doc("b.pdf", vendor_name="Birch Coffee", total=Decimal("7.25"), invoice_date=date(2025, 2, 10),
            status=DocumentStatus.NEEDS_REVIEW, document_type=DocumentType.RECEIPT),
        doc("c_scan.pdf", vendor_name=None, total=None, status=DocumentStatus.UPLOADED),
    ]  # fmt: skip
    for d in docs:  # distinct created_at so sort order is deterministic
        db_session.add(d)
        db_session.commit()
    return docs


def names(response) -> list[str]:
    return [item["original_filename"] for item in response.json()["items"]]


def test_list_defaults_to_newest_first(client: TestClient, seeded) -> None:
    response = client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3 and body["limit"] == 50 and body["offset"] == 0
    assert names(response) == ["c_scan.pdf", "b.pdf", "a.pdf"]
    assert body["items"][2]["total"] == 50.0  # money serialised as a JSON number


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "birch"}, ["b.pdf"]),
        ({"q": "100%"}, ["a.pdf"]),  # % is matched literally, not as a wildcard
        ({"q": "_scan"}, ["c_scan.pdf"]),
        ({"status": ["COMPLETED", "NEEDS_REVIEW"]}, ["b.pdf", "a.pdf"]),
        ({"document_type": "RECEIPT"}, ["b.pdf"]),
        ({"date_from": "2025-02-01"}, ["b.pdf"]),
        ({"date_to": "2025-01-31"}, ["a.pdf"]),
        ({"sort": "oldest"}, ["a.pdf", "b.pdf", "c_scan.pdf"]),
        ({"sort": "amount_desc"}, ["a.pdf", "b.pdf", "c_scan.pdf"]),
        ({"sort": "amount_asc"}, ["b.pdf", "a.pdf", "c_scan.pdf"]),  # NULL totals last
        ({"sort": "vendor"}, ["a.pdf", "b.pdf", "c_scan.pdf"]),
    ],
)
def test_list_filters_and_sorting(client: TestClient, seeded, params, expected) -> None:
    assert names(client.get("/api/documents", params=params)) == expected


def test_list_pagination(client: TestClient, seeded) -> None:
    body = client.get("/api/documents", params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 3
    assert [i["original_filename"] for i in body["items"]] == ["a.pdf"]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "DONE"}, {"sort": "x"}]
)
def test_list_rejects_invalid_query(client: TestClient, params) -> None:
    response = client.get("/api/documents", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


# --- Detail / file / delete -------------------------------------------------


def test_get_document_detail(client: TestClient) -> None:
    document_id = upload(client, make_pdf(), "invoice.pdf").json()["id"]

    response = client.get(f"/api/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == document_id
    # Processing ran in the background before the client call returned (TestClient semantics).
    assert body["status"] == "COMPLETED"
    assert [p["page_number"] for p in body["pages"]] == [1]
    # Extraction ran too (Phase 4): the sample invoice is complete and consistent.
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["invoice_number"]["value"] == "INV-2041" and fields["total"]["normalized_value"] == "54.00"
    assert body["document_type"] == "INVOICE" and body["total"] == 54.0
    assert len(body["line_items"]) == 1 and body["warnings"] == []


def test_unknown_document_is_404_and_bad_id_is_422(client: TestClient) -> None:
    missing = client.get(f"/api/documents/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "document_not_found"

    assert client.get("/api/documents/not-a-uuid").status_code == 422
    assert client.delete(f"/api/documents/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/documents/{uuid.uuid4()}/file").status_code == 404


def test_download_original_file(client: TestClient) -> None:
    content = make_png()
    document_id = upload(client, content, "Café receipt.png", "image/png").json()["id"]

    response = client.get(f"/api/documents/{document_id}/file")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert 'filename="Caf_ receipt.png"' in disposition
    assert "filename*=UTF-8''Caf%C3%A9%20receipt.png" in disposition


def test_download_when_stored_file_is_missing(client: TestClient, db_session: Session, storage) -> None:
    document_id = upload(client, make_pdf(), "invoice.pdf").json()["id"]
    storage.delete(db_session.get(Document, uuid.UUID(document_id)).storage_key)

    response = client.get(f"/api/documents/{document_id}/file")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"


def test_delete_removes_row_children_and_file(client: TestClient, db_session: Session, storage) -> None:
    document_id = uuid.UUID(upload(client, make_pdf(), "invoice.pdf").json()["id"])
    db_session.add_all(
        [
            DocumentPage(
                document_id=document_id, page_number=2, text="Invoice"
            ),  # page 1 came from processing
            LineItem(document_id=document_id, position=1, description="Widget", total=Decimal("10.00")),
            ValidationWarning(document_id=document_id, code="total_mismatch", message="Totals differ."),
        ]
    )
    db_session.commit()

    for model in (DocumentPage, ExtractedField, LineItem, ValidationWarning):  # processing created rows
        assert db_session.scalar(select(func.count()).select_from(model)) > 0

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(Document, document_id) is None
    for model in (DocumentPage, ExtractedField, LineItem, ValidationWarning):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
    assert stored_files(storage) == []
    assert list((storage.root / "previews").rglob("*.png")) == []  # page previews removed too
    assert client.get(f"/api/documents/{document_id}").status_code == 404


def test_oversized_upload_is_rejected_before_the_body_is_parsed(
    settings: Settings, db_session: Session
) -> None:
    # A small app-level limit so the Content-Length check (not the service) rejects the request.
    small = settings.model_copy(update={"max_upload_size": 1024})
    app = create_app(small)
    app.dependency_overrides[get_settings] = lambda: small
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as small_client:
        response = upload(small_client, b"%PDF-" + b"0" * 200_000, "big.pdf")

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "file_too_large"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert not (small.storage_path / "originals").exists()  # never reached the storage layer
