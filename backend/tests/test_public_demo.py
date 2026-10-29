"""Public-demo safeguards: private workspaces, limits, retention, database storage, SPA serving."""

import io
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.api.deps import get_ocr_service
from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError
from app.core.rate_limit import SlidingWindowLimiter, client_ip
from app.core.workspace import LOCAL_WORKSPACE, workspace_id_from_token
from app.db.base import utcnow
from app.db.session import get_db, get_session_factory
from app.main import create_app
from app.models import Document, DocumentPage, StoredFile
from app.services.retention_service import purge_expired
from app.services.storage import DatabaseStorage, InvalidStorageKeyError, StorageObjectNotFoundError
from tests import invoice_texts as T
from tests.conftest import FakeOCR
from tests.samples import make_text_pdf

ALICE = "a" * 40
BOB = "b" * 40


def make_client(settings: Settings, db_session, session_factory, fake_ocr: FakeOCR) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_ocr_service] = lambda: fake_ocr
    return TestClient(app)


@pytest.fixture
def demo(settings, db_session, session_factory, fake_ocr):
    """Factory for a client configured like the public deployment."""

    def _make(**overrides) -> TestClient:
        config = settings.model_copy(update={"demo_mode": True, "storage_backend": "database", **overrides})
        return make_client(config, db_session, session_factory, fake_ocr)

    return _make


def upload(client: TestClient, token: str | None, text: str = T.STANDARD_INVOICE):
    headers = {"X-Workspace-Token": token} if token else {}
    return client.post(
        "/api/documents/upload",
        files={"file": ("invoice.pdf", make_text_pdf(text), "application/pdf")},
        headers=headers,
    )


# --- Workspaces ---------------------------------------------------------------


def test_token_hashing() -> None:
    assert workspace_id_from_token(None, required=False) == LOCAL_WORKSPACE
    hashed = workspace_id_from_token(ALICE, required=True)
    assert len(hashed) == 64 and ALICE not in hashed  # only the hash is stored


def test_demo_mode_requires_a_well_formed_token(demo) -> None:
    with demo() as client:
        missing = client.get("/api/documents")
        assert missing.status_code == 401 and missing.json()["error"]["code"] == "workspace_required"
        short = client.get("/api/documents", headers={"X-Workspace-Token": "short"})
        assert short.status_code == 422 and short.json()["error"]["code"] == "invalid_workspace_token"
        assert client.get("/api/health").status_code == 200  # public endpoints stay open
        assert client.get("/api/meta").json()["demo_mode"] is True


def test_workspaces_are_isolated_on_every_endpoint(demo) -> None:
    with demo() as client:
        doc_id = upload(client, ALICE).json()["id"]
        alice, bob = {"X-Workspace-Token": ALICE}, {"X-Workspace-Token": BOB}

        assert client.get("/api/documents", headers=alice).json()["total"] == 1
        assert client.get("/api/documents", headers=bob).json()["total"] == 0
        for method, path in [
            ("get", f"/api/documents/{doc_id}"),
            ("get", f"/api/documents/{doc_id}/status"),
            ("get", f"/api/documents/{doc_id}/extraction"),
            ("get", f"/api/documents/{doc_id}/file"),
            ("get", f"/api/documents/{doc_id}/pages/1/preview"),
            ("post", f"/api/documents/{doc_id}/process"),
            ("delete", f"/api/documents/{doc_id}"),
        ]:
            response = getattr(client, method)(path, headers=bob)
            assert response.status_code == 404, (method, path)  # indistinguishable from "doesn't exist"
            assert getattr(client, method)(path, headers=alice).status_code != 404 or method == "delete"
        patch = client.patch(f"/api/documents/{doc_id}/extraction", json={"fields": {}}, headers=bob)
        assert patch.status_code == 404
        assert client.get("/api/analytics/overview", headers=bob).json()["total_documents"] == 0


def test_delete_all_only_touches_own_workspace(demo, db_session: Session) -> None:
    with demo() as client:
        upload(client, ALICE)
        upload(client, ALICE)
        upload(client, BOB)
        assert client.delete("/api/documents", headers={"X-Workspace-Token": ALICE}).json() == {"deleted": 2}
        assert client.get("/api/documents", headers={"X-Workspace-Token": BOB}).json()["total"] == 1
        assert db_session.scalar(select(func.count()).select_from(Document)) == 1


# --- Limits ---------------------------------------------------------------------


def test_upload_rate_limit(demo) -> None:
    with demo(upload_rate_limit_per_hour=2) as client:
        assert upload(client, ALICE).status_code == 202
        assert upload(client, BOB).status_code == 202  # limit is per network, not per workspace
        third = upload(client, ALICE)
        assert third.status_code == 429
        error = third.json()["error"]
        assert error["code"] == "rate_limited" and error["details"]["limit_per_hour"] == 2


def test_limiter_counts_per_key() -> None:
    limiter = SlidingWindowLimiter(limit=1)
    limiter.hit("1.1.1.1")
    limiter.hit("2.2.2.2")
    with pytest.raises(RateLimitedError):
        limiter.hit("1.1.1.1")
    SlidingWindowLimiter(limit=0).hit("x")  # 0 disables


def test_client_ip_trusts_forwarded_for_only_when_configured() -> None:
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")],
        "client": ("10.0.0.1", 1),
    }
    request = Request(scope)
    assert client_ip(request, trust_proxy=True) == "203.0.113.9"  # behind Render's proxy
    assert client_ip(request, trust_proxy=False) == "10.0.0.1"  # otherwise the header is spoofable


def test_workspace_document_cap(demo) -> None:
    with demo(max_documents_per_workspace=1) as client:
        assert upload(client, ALICE).status_code == 202
        second = upload(client, ALICE)
        assert second.status_code == 409 and second.json()["error"]["code"] == "workspace_limit_reached"
        assert upload(client, BOB).status_code == 202


# --- Retention ------------------------------------------------------------------


def test_retention_purges_old_documents_and_files(
    demo, db_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with demo() as client:
        old_id = uuid.UUID(upload(client, ALICE).json()["id"])
        new_id = uuid.UUID(upload(client, ALICE).json()["id"])
    old = db_session.get(Document, old_id)
    old.created_at = utcnow() - timedelta(hours=30)
    db_session.commit()
    old_keys = [old.storage_key] + [p.preview_key for p in old.pages]

    deleted = purge_expired(session_factory, DatabaseStorage(session_factory), retention_hours=24)

    assert deleted == 1
    db_session.expire_all()
    assert db_session.get(Document, old_id) is None and db_session.get(Document, new_id) is not None
    assert (
        db_session.scalar(
            select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == old_id)
        )
        == 0
    )
    assert all(db_session.get(StoredFile, key) is None for key in old_keys)
    assert purge_expired(session_factory, DatabaseStorage(session_factory), retention_hours=0) == 0


# --- Database storage -------------------------------------------------------------


def test_database_storage_roundtrip(session_factory) -> None:
    storage = DatabaseStorage(session_factory)
    assert storage.save("originals/x.pdf", io.BytesIO(b"one")) == 3
    assert storage.save("originals/x.pdf", io.BytesIO(b"second")) == 6  # overwrite
    assert storage.exists("originals/x.pdf")
    assert b"".join(storage.iter_chunks("originals/x.pdf", chunk_size=2)) == b"second"
    assert storage.delete("originals/x.pdf") is True and storage.delete("originals/x.pdf") is False
    with pytest.raises(StorageObjectNotFoundError):
        storage.open("originals/x.pdf")
    with pytest.raises(InvalidStorageKeyError):
        storage.save("../etc/passwd", io.BytesIO(b"x"))


def test_full_flow_with_database_storage(demo, db_session: Session) -> None:
    with demo() as client:
        headers = {"X-Workspace-Token": ALICE}
        doc_id = upload(client, ALICE).json()["id"]
        assert client.get(f"/api/documents/{doc_id}/status", headers=headers).json()["status"] == "COMPLETED"
        assert client.get(f"/api/documents/{doc_id}/pages/1/preview", headers=headers).status_code == 200
        original = client.get(f"/api/documents/{doc_id}/file", headers=headers)
        assert original.status_code == 200 and original.content.startswith(b"%PDF")
        assert db_session.scalar(select(func.count()).select_from(StoredFile)) == 2  # original + preview
        client.delete(f"/api/documents/{doc_id}", headers=headers)
        assert db_session.scalar(select(func.count()).select_from(StoredFile)) == 0


# --- Meta, config, SPA, headers -------------------------------------------------------


def test_meta_reports_limits(demo) -> None:
    with demo(retention_hours=24, upload_rate_limit_per_hour=20, max_documents_per_workspace=25) as client:
        meta = client.get("/api/meta").json()
    assert meta | {"version": None} == {
        "version": None,
        "demo_mode": True,
        "retention_hours": 24,
        "max_upload_bytes": 15 * 1024 * 1024,
        "max_pages": 50,
        "max_documents_per_workspace": 25,
        "upload_rate_limit_per_hour": 20,
        "accepted_types": ["application/pdf", "image/png", "image/jpeg"],
        "date_order": "DMY",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_database_url_is_normalized_for_psycopg(monkeypatch, raw: str, expected: str) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)
    assert Settings().database_url == expected


def test_spa_is_served_without_shadowing_the_api(
    settings, db_session, session_factory, fake_ocr, tmp_path: Path
):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>DocuMind SPA</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    config = settings.model_copy(update={"static_dir": dist})

    with make_client(config, db_session, session_factory, fake_ocr) as client:
        for path in ("/", "/app/dashboard", "/app/documents/123"):  # client-side routes → index.html
            response = client.get(path)
            assert response.status_code == 200 and "DocuMind SPA" in response.text, path
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/api/health").json()["status"] in ("ok", "degraded")
        missing_api = client.get("/api/nope")
        assert missing_api.status_code == 404 and missing_api.json()["error"]["code"] == "not_found"
        assert client.get("/../backend/.env").status_code in (200, 404)  # normalized by the client → index
        assert "DocuMind SPA" in client.get("/%2e%2e/%2e%2e/README.md").text  # traversal never escapes dist


def test_security_headers_on_api_responses(client: TestClient) -> None:
    headers = client.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_cors_allows_the_workspace_header(client: TestClient) -> None:
    preflight = client.options(
        "/api/documents",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-workspace-token",
        },
    )
    assert preflight.status_code == 200
    assert "x-workspace-token" in preflight.headers["access-control-allow-headers"].lower()
