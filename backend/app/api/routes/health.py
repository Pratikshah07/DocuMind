import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import check_database, get_db
from app.schemas.health import ComponentHealth, HealthResponse

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
) -> HealthResponse:
    components: dict[str, ComponentHealth] = {}

    try:
        check_database(db)
        components["database"] = ComponentHealth(status="ok")
    except Exception as exc:
        logger.warning("health_db_unreachable", extra={"error_type": type(exc).__name__})
        components["database"] = ComponentHealth(status="error", detail="Database is unreachable.")

    overall = "ok" if all(c.status != "error" for c in components.values()) else "degraded"
    return HealthResponse(
        status=overall,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
