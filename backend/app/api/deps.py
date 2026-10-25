"""Dependency providers. Routes ask for services; tests override these."""

from typing import Annotated

from fastapi import BackgroundTasks, Depends
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_db, get_session_factory
from app.services.document_service import DocumentService
from app.services.jobs import BackgroundTaskRunner, JobRunner
from app.services.ocr import OCRService, TesseractOCR
from app.services.pipeline import DocumentProcessor, ProcessorConfig
from app.services.processing_service import ProcessingService
from app.services.storage import LocalStorage, StorageBackend

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def get_storage(settings: SettingsDep) -> StorageBackend:
    return LocalStorage(settings.storage_path)


StorageDep = Annotated[StorageBackend, Depends(get_storage)]


def get_ocr_service(settings: SettingsDep) -> OCRService:
    return TesseractOCR(
        cmd=settings.tesseract_cmd,
        language=settings.ocr_language,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


OCRDep = Annotated[OCRService, Depends(get_ocr_service)]


def get_job_runner(background_tasks: BackgroundTasks) -> JobRunner:
    return BackgroundTaskRunner(background_tasks)


def get_document_processor(
    session_factory: SessionFactoryDep, storage: StorageDep, ocr: OCRDep, settings: SettingsDep
) -> DocumentProcessor:
    config = ProcessorConfig(
        max_pages=settings.max_pages,
        max_image_pixels=settings.max_image_pixels,
        pdf_min_text_chars=settings.pdf_min_text_chars,
        ocr_render_dpi=settings.ocr_render_dpi,
        preview_max_width=settings.preview_max_width,
        pdf_steps=tuple(settings.preprocess_pdf_steps),
        image_steps=tuple(settings.preprocess_image_steps),
    )
    return DocumentProcessor(session_factory, storage, ocr, config)


def get_document_service(db: DbDep, storage: StorageDep, settings: SettingsDep) -> DocumentService:
    return DocumentService(db, storage, max_upload_size=settings.max_upload_size)


def get_processing_service(
    db: DbDep,
    runner: Annotated[JobRunner, Depends(get_job_runner)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
    settings: SettingsDep,
) -> ProcessingService:
    return ProcessingService(
        db, runner, processor, stale_after_seconds=settings.processing_stale_after_seconds
    )


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ProcessingServiceDep = Annotated[ProcessingService, Depends(get_processing_service)]
