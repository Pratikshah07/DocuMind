"""Dependency providers. Routes ask for services; tests override these."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.document_service import DocumentService
from app.services.storage import LocalStorage, StorageBackend

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def get_storage(settings: SettingsDep) -> StorageBackend:
    return LocalStorage(settings.storage_path)


StorageDep = Annotated[StorageBackend, Depends(get_storage)]


def get_document_service(db: DbDep, storage: StorageDep, settings: SettingsDep) -> DocumentService:
    return DocumentService(db, storage, max_upload_size=settings.max_upload_size)


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
