import uuid

from fastapi import APIRouter, status

from app.api.deps import ProcessingServiceDep
from app.core.errors import error_responses
from app.models import Document, ProcessingJob
from app.schemas.processing import DocumentStatusResponse, ProcessingJobOut

router = APIRouter(prefix="/documents", tags=["processing"])


def _status(document: Document, job: ProcessingJob | None) -> DocumentStatusResponse:
    return DocumentStatusResponse(
        document_id=document.id,
        status=document.status,
        page_count=document.page_count,
        error_message=document.error_message,
        processed_at=document.processed_at,
        job=ProcessingJobOut.model_validate(job) if job else None,
    )


@router.post(
    "/{document_id}/process",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentStatusResponse,
    summary="(Re)process a document",
    description=(
        "Queues a new processing attempt. Used for retries after `FAILED` and for reprocessing. "
        "Returns 409 `already_processing` while an attempt is queued or running."
    ),
    responses=error_responses(404, 409, 422),
)
def process_document(document_id: uuid.UUID, service: ProcessingServiceDep) -> DocumentStatusResponse:
    job = service.enqueue(document_id)
    document, _ = service.status(document_id)
    return _status(document, job)


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Processing status",
    description="Current document status plus the latest processing job (stage, timing, error code).",
    responses=error_responses(404, 422),
)
def get_document_status(document_id: uuid.UUID, service: ProcessingServiceDep) -> DocumentStatusResponse:
    return _status(*service.status(document_id))
