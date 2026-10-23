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
