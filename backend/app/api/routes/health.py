import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_ocr_service
from app.core.config import Settings, get_settings
from app.db.session import check_database, get_db
from app.schemas.health import ComponentHealth, HealthResponse, MetaResponse
from app.services.ocr import OCRService, OCRUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description=(
        "Reports overall status and the state of each backing component. "
        "Always returns 200 so load balancers can distinguish 'up but degraded' from 'down'."
    ),
)
def health(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr: Annotated[OCRService, Depends(get_ocr_service)],
) -> HealthResponse:
    components: dict[str, ComponentHealth] = {}

    try:
        check_database(db)
        components["database"] = ComponentHealth(status="ok")
    except Exception as exc:
        logger.warning("health_db_unreachable", extra={"error_type": type(exc).__name__})
        components["database"] = ComponentHealth(status="error", detail="Database is unreachable.")

    try:
        ocr.check_available()
        components["ocr"] = ComponentHealth(status="ok")
    except OCRUnavailableError:
        components["ocr"] = ComponentHealth(
            status="error", detail="OCR engine (Tesseract) is not available; scanned documents will fail."
        )

    overall = "ok" if all(c.status != "error" for c in components.values()) else "degraded"
    return HealthResponse(
        status=overall,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="Public server limits",
    description="Demo mode, retention, upload limits and accepted file types, for display in the UI.",
)
def meta(settings: Annotated[Settings, Depends(get_settings)]) -> MetaResponse:
    return MetaResponse(
        version=settings.app_version,
        demo_mode=settings.demo_mode,
        retention_hours=settings.retention_hours,
        max_upload_bytes=settings.max_upload_size,
        max_pages=settings.max_pages,
        max_documents_per_workspace=settings.max_documents_per_workspace,
        upload_rate_limit_per_hour=settings.upload_rate_limit_per_hour,
        accepted_types=["application/pdf", "image/png", "image/jpeg"],
        date_order=settings.date_order,
    )
