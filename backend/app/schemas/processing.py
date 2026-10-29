import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import DocumentStatus, JobStatus
from app.services.processing_errors import is_retryable


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

    @computed_field(description="Whether retrying the same file can help (null when the job did not fail).")
    @property
    def retryable(self) -> bool | None:
        return is_retryable(self.error_code)


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    page_count: int | None
    error_message: str | None = Field(description="User-safe explanation when status is FAILED.")
    processed_at: datetime | None
    job: ProcessingJobOut | None = Field(description="Most recent processing attempt, if any.")
