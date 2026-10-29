"""Dependency providers. Routes ask for services; tests override these."""

from typing import Annotated

from fastapi import BackgroundTasks, Depends, Header, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.rate_limit import SlidingWindowLimiter, client_ip
from app.core.workspace import workspace_id_from_token
from app.db.session import get_db, get_session_factory
from app.services.analytics_service import AnalyticsService
from app.services.document_service import DocumentService
from app.services.extraction_service import ExtractionEngine, ExtractionService, extraction_config
from app.services.jobs import BackgroundTaskRunner, JobRunner
from app.services.ocr import OCRService, TesseractOCR
from app.services.pipeline import DocumentProcessor, ProcessorConfig
from app.services.processing_service import ProcessingService
from app.services.storage import DatabaseStorage, LocalStorage, StorageBackend

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def build_storage(settings: Settings, session_factory: sessionmaker[Session]) -> StorageBackend:
    if settings.storage_backend == "database":
        return DatabaseStorage(session_factory)
    return LocalStorage(settings.storage_path)


def get_storage(settings: SettingsDep, session_factory: SessionFactoryDep) -> StorageBackend:
    return build_storage(settings, session_factory)


StorageDep = Annotated[StorageBackend, Depends(get_storage)]


def get_workspace_id(
    settings: SettingsDep,
    x_workspace_token: Annotated[
        str | None,
        Header(
            description="Random per-browser token (32–128 chars of A–Z a–z 0–9 _ -). "
            "Documents are private to it. Required when the server runs in demo mode."
        ),
    ] = None,
) -> str:
    return workspace_id_from_token(x_workspace_token, required=settings.demo_mode)


WorkspaceDep = Annotated[str, Depends(get_workspace_id)]


def limit_expensive_actions(request: Request, settings: SettingsDep) -> None:
    """Per-IP rate limit for uploads and reprocessing (UPLOAD_RATE_LIMIT_PER_HOUR)."""
    limiter: SlidingWindowLimiter = request.app.state.upload_limiter
    limiter.hit(client_ip(request, trust_proxy=settings.trust_proxy_headers))


RateLimited = Depends(limit_expensive_actions)


def get_ocr_service(settings: SettingsDep) -> OCRService:
    return TesseractOCR(
        cmd=settings.tesseract_cmd,
        language=settings.ocr_language,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


OCRDep = Annotated[OCRService, Depends(get_ocr_service)]


def get_extraction_engine(settings: SettingsDep) -> ExtractionEngine:
    return ExtractionEngine(extraction_config(settings))


ExtractionEngineDep = Annotated[ExtractionEngine, Depends(get_extraction_engine)]


def get_job_runner(background_tasks: BackgroundTasks) -> JobRunner:
    return BackgroundTaskRunner(background_tasks)


def get_document_processor(
    session_factory: SessionFactoryDep,
    storage: StorageDep,
    ocr: OCRDep,
    extraction: ExtractionEngineDep,
    settings: SettingsDep,
) -> DocumentProcessor:
    config = ProcessorConfig(
        max_pages=settings.max_pages,
        max_image_pixels=settings.max_image_pixels,
        pdf_min_text_chars=settings.pdf_min_text_chars,
        ocr_render_dpi=settings.ocr_render_dpi,
        preview_max_width=settings.preview_max_width,
        pdf_steps=tuple(settings.preprocess_pdf_steps),
        image_steps=tuple(settings.preprocess_image_steps),
        max_concurrent_jobs=settings.max_concurrent_jobs,
    )
    return DocumentProcessor(session_factory, storage, ocr, config, extraction)


def get_document_service(
    db: DbDep, storage: StorageDep, settings: SettingsDep, workspace_id: WorkspaceDep
) -> DocumentService:
    return DocumentService(
        db,
        storage,
        max_upload_size=settings.max_upload_size,
        workspace_id=workspace_id,
        max_documents=settings.max_documents_per_workspace,
    )


def get_processing_service(
    db: DbDep,
    runner: Annotated[JobRunner, Depends(get_job_runner)],
    processor: Annotated[DocumentProcessor, Depends(get_document_processor)],
    settings: SettingsDep,
    workspace_id: WorkspaceDep,
) -> ProcessingService:
    return ProcessingService(
        db,
        runner,
        processor,
        stale_after_seconds=settings.processing_stale_after_seconds,
        workspace_id=workspace_id,
    )


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
ProcessingServiceDep = Annotated[ProcessingService, Depends(get_processing_service)]


def get_extraction_service(db: DbDep, settings: SettingsDep, workspace_id: WorkspaceDep) -> ExtractionService:
    return ExtractionService(db, extraction_config(settings), workspace_id=workspace_id)


ExtractionServiceDep = Annotated[ExtractionService, Depends(get_extraction_service)]


def get_analytics_service(db: DbDep, workspace_id: WorkspaceDep) -> AnalyticsService:
    return AnalyticsService(db, workspace_id=workspace_id)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
