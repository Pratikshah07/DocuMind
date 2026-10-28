import uuid

from fastapi import APIRouter

from app.api.deps import ExtractionServiceDep, SettingsDep
from app.core.errors import error_responses
from app.schemas.extraction import DocumentExtractionResponse, ExtractionUpdateRequest, build_response
from app.services.extraction_service import validation_config

router = APIRouter(prefix="/documents", tags=["extraction"])


@router.get(
    "/{document_id}/extraction",
    response_model=DocumentExtractionResponse,
    summary="Structured extraction",
    description=(
        "Extracted fields with status (ok / uncertain / invalid / missing), confidence and provenance, "
        "line items, and validation warnings. 409 `extraction_not_ready` until processing has finished."
    ),
    responses=error_responses(404, 409, 422),
)
def get_extraction(
    document_id: uuid.UUID, service: ExtractionServiceDep, settings: SettingsDep
) -> DocumentExtractionResponse:
    document, outcome = service.get(document_id)
    return build_response(document, outcome, validation_config(settings))


@router.patch(
    "/{document_id}/extraction",
    response_model=DocumentExtractionResponse,
    summary="Correct extracted values",
    description=(
        "Apply user corrections, then re-run validation. Edited fields get method `user`, confidence 1.0 "
        "and `is_user_edited`; warnings about how an edited value was read are dropped, and every "
        "cross-field rule is re-checked. The document becomes COMPLETED or NEEDS_REVIEW accordingly. "
        "Invalid values are rejected with 422 and nothing is changed."
    ),
    responses=error_responses(404, 409, 422),
)
def update_extraction(
    document_id: uuid.UUID,
    body: ExtractionUpdateRequest,
    service: ExtractionServiceDep,
    settings: SettingsDep,
) -> DocumentExtractionResponse:
    document, outcome = service.update(document_id, body.to_update())
    return build_response(document, outcome, validation_config(settings))
