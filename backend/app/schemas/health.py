from typing import Literal

from pydantic import BaseModel, Field

ComponentState = Literal["ok", "error", "disabled"]


class ComponentHealth(BaseModel):
    status: ComponentState
    detail: str | None = Field(default=None, description="Short, non-sensitive explanation when not ok.")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        description="`ok` when every enabled component is healthy, otherwise `degraded`."
    )
    version: str
    environment: str
    components: dict[str, ComponentHealth]


class MetaResponse(BaseModel):
    """Public, non-sensitive server limits so the UI can describe them accurately."""

    version: str
    demo_mode: bool = Field(description="Workspaces are private per browser; a token header is required.")
    retention_hours: int = Field(description="Documents are deleted after this many hours (0 = kept).")
    max_upload_bytes: int
    max_pages: int
    max_documents_per_workspace: int = Field(description="0 = unlimited.")
    upload_rate_limit_per_hour: int = Field(
        description="Uploads + reprocessing per network per hour; 0 = unlimited."
    )
    accepted_types: list[str]
    date_order: str
