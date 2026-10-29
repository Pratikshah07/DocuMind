"""FastAPI application factory."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import build_storage
from app.api.routes import analytics, documents, extraction, health, processing
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    UploadSizeLimitMiddleware,
)
from app.core.rate_limit import SlidingWindowLimiter
from app.core.workspace import WORKSPACE_HEADER
from app.db.session import get_sessionmaker
from app.services.maintenance_service import recover_interrupted_jobs, sweep_orphans
from app.services.retention_service import purge_expired

logger = logging.getLogger(__name__)


def run_maintenance(settings: Settings, *, startup: bool) -> None:
    """One housekeeping pass. Each step is independent: one failing doesn't skip the others."""
    factory = get_sessionmaker()
    storage = build_storage(settings, factory)
    stale = timedelta(seconds=settings.processing_stale_after_seconds)
    steps = [
        ("retention", lambda: purge_expired(factory, storage, settings.retention_hours)),
        (
            "job_recovery",
            lambda: recover_interrupted_jobs(
                factory, storage, older_than=None if startup and settings.recover_jobs_on_startup else stale
            ),
        ),
        # Grace of 2x the stale timeout: an upload or a run in progress is never swept.
        ("orphan_sweep", lambda: sweep_orphans(factory, storage, grace=2 * stale)),
    ]
    for name, step in steps:
        try:
            step()
        except Exception:
            logger.exception("maintenance_step_failed", extra={"step": name})


async def _maintenance_loop(settings: Settings) -> None:
    startup = True
    while True:
        await asyncio.to_thread(run_maintenance, settings, startup=startup)
        startup = False
        await asyncio.sleep(settings.maintenance_interval_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = (
            asyncio.create_task(_maintenance_loop(settings))
            if settings.maintenance_interval_seconds
            else None
        )
        yield
        if task:
            task.cancel()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "DocuMind turns invoices and receipts into structured data: upload, OCR, "
            "extraction with confidence scores, validation and analytics."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )
    app.state.upload_limiter = SlidingWindowLimiter(settings.upload_rate_limit_per_hour)

    # Middleware order: the last added runs first. CORS must wrap everything so
    # error responses also carry CORS headers; the size limit runs inside the
    # request context so its 413 carries a request ID.
    app.add_middleware(
        UploadSizeLimitMiddleware,
        paths=(f"{settings.api_prefix}/documents/upload",),
        max_body_size=settings.max_upload_size,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, WORKSPACE_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
    )

    register_exception_handlers(app)
    for module in (health, documents, processing, extraction, analytics):
        app.include_router(module.router, prefix=settings.api_prefix)

    if settings.static_dir:
        _mount_spa(app, settings.static_dir, settings.api_prefix)

    logger.info(
        "app_started",
        extra={
            "environment": settings.environment,
            "version": settings.app_version,
            "demo_mode": settings.demo_mode,
            "storage_backend": settings.storage_backend,
        },
    )
    return app


def _mount_spa(app: FastAPI, static_dir: Path, api_prefix: str) -> None:
    """Serve the built frontend: hashed assets as static files, every other path → index.html."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        logger.warning("static_dir_missing_index", extra={"static_dir": str(static_dir)})
        return
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")
    api = api_prefix.strip("/")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == api or path.startswith(api + "/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):  # favicon.svg, robots.txt
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
