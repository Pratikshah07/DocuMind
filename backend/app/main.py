"""FastAPI application factory."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import documents, extraction, health, processing
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware, UploadSizeLimitMiddleware

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "DocuMind turns invoices and receipts into structured data: upload, OCR, "
            "extraction with confidence scores, validation, analytics and document Q&A."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    # Middleware order: the last added runs first. CORS must wrap everything so
    # error responses also carry CORS headers; the size limit runs inside the
    # request context so its 413 carries a request ID.
    app.add_middleware(
        UploadSizeLimitMiddleware,
        paths=(f"{settings.api_prefix}/documents/upload",),
        max_body_size=settings.max_upload_size,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(documents.router, prefix=settings.api_prefix)
    app.include_router(processing.router, prefix=settings.api_prefix)
    app.include_router(extraction.router, prefix=settings.api_prefix)

    logger.info("app_started", extra={"environment": settings.environment, "version": settings.app_version})
    return app


app = create_app()
