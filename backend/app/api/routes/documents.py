import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import DocumentServiceDep, ProcessingServiceDep
from app.core.errors import error_responses
from app.schemas.document import (
    DocumentDetail,
    DocumentFilters,
    DocumentListResponse,
    DocumentSummary,
    DocumentUploadResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentUploadResponse,
    summary="Upload a document",
    description=(
        "Upload one PDF, PNG or JPEG (multipart field `file`). The type is detected from the file's "
        "content; the extension and declared Content-Type must agree with it. The document is stored "
        "with status `UPLOADED` and processing is queued; poll `GET /documents/{id}/status`."
    ),
    responses=error_responses(413, 415, 422),
)
def upload_document(
    service: DocumentServiceDep,
    processing: ProcessingServiceDep,
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="PDF, PNG or JPEG file.")],
) -> DocumentUploadResponse:
    document = service.upload(filename=file.filename, content_type=file.content_type, stream=file.file)
    job = processing.enqueue(document.id)
    response.headers["Location"] = str(request.url_for("get_document", document_id=document.id).path)
    return DocumentUploadResponse(
        id=document.id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        status=document.status,
        created_at=document.created_at,
        job_id=job.id,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="Search, filter, sort and paginate documents. `status` may be repeated.",
    responses=error_responses(422),
)
def list_documents(
    service: DocumentServiceDep,
    filters: Annotated[DocumentFilters, Query()],
) -> DocumentListResponse:
    items, total = service.list(filters)
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(d) for d in items],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get a document",
    description="Document metadata with pages, extracted fields, line items and validation warnings.",
    responses=error_responses(404, 422),
)
def get_document(document_id: uuid.UUID, service: DocumentServiceDep) -> DocumentDetail:
    return DocumentDetail.model_validate(service.get(document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description="Deletes the document, its extraction results and its stored file.",
    responses=error_responses(404, 422),
)
def delete_document(document_id: uuid.UUID, service: DocumentServiceDep) -> Response:
    service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _content_disposition(filename: str) -> str:
    # ASCII fallback for old clients plus RFC 5987 UTF-8 name; quotes/backslashes can't break the header.
    ascii_name = (
        filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_").replace("\\", "_")
    )
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get(
    "/{document_id}/pages/{page_number}/preview",
    response_class=StreamingResponse,
    summary="Page preview image",
    description="PNG rendering of one page (1-based), created during processing.",
    responses={200: {"content": {"image/png": {}}}} | error_responses(404, 422),
)
def get_page_preview(
    document_id: uuid.UUID, page_number: int, service: DocumentServiceDep
) -> StreamingResponse:
    chunks = service.open_preview(document_id, page_number)
    return StreamingResponse(
        chunks,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get(
    "/{document_id}/file",
    response_class=StreamingResponse,
    summary="Download the original file",
    description="Streams the original upload. The storage location is never exposed.",
    responses={200: {"content": {"application/pdf": {}, "image/png": {}, "image/jpeg": {}}}}
    | error_responses(404, 422),
)
def get_document_file(document_id: uuid.UUID, service: DocumentServiceDep) -> StreamingResponse:
    document, chunks = service.open_file(document_id)
    return StreamingResponse(
        chunks,
        media_type=document.mime_type,
        headers={
            "Content-Length": str(document.size_bytes),
            "Content-Disposition": _content_disposition(document.original_filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
