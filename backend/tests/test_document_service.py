"""Consistency between the database and file storage when one side fails."""

import io

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Document
from app.services.document_service import DocumentService
from app.services.storage import LocalStorage
from tests.samples import make_pdf


def make_service(db: Session, storage: LocalStorage) -> DocumentService:
    return DocumentService(db, storage, max_upload_size=1024 * 1024)


def test_failed_commit_removes_the_stored_file(
    db_session: Session, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_commit() -> None:
        raise OperationalError("INSERT", {}, Exception("connection lost"))

    monkeypatch.setattr(db_session, "commit", broken_commit)

    with pytest.raises(OperationalError):
        make_service(db_session, storage).upload(
            filename="invoice.pdf", content_type="application/pdf", stream=io.BytesIO(make_pdf())
        )

    assert list((storage.root / "originals").iterdir()) == []
    monkeypatch.undo()
    assert db_session.scalar(select(func.count()).select_from(Document)) == 0


def test_file_delete_failure_still_deletes_the_row(
    db_session: Session, storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(db_session, storage)
    document = service.upload(filename="invoice.pdf", content_type=None, stream=io.BytesIO(make_pdf()))

    def broken_delete(key: str) -> bool:
        raise PermissionError("file locked")

    monkeypatch.setattr(storage, "delete", broken_delete)
    service.delete(document.id)  # does not raise: the orphaned file is logged

    db_session.expire_all()
    assert db_session.get(Document, document.id) is None
