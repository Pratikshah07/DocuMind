import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentStatus, JobStatus


class ProcessingJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    stage: DocumentStatus | None = Field(description="Last stage the job reached.")
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error_code: str | None = Field(description="Stable machine-readable failure code, e.g. `corrupt_pdf`.")
    created_at: datetime


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    page_count: int | None
    error_message: str | None = Field(description="User-safe explanation when status is FAILED.")
    processed_at: datetime | None
    job: ProcessingJobOut | None = Field(description="Most recent processing attempt, if any.")
