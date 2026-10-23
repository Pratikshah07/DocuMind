"""Request-ID / access-log and upload size-limit middleware."""

import logging
import time
import uuid

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_response
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept a caller-supplied ID only if it looks sane; otherwise mint one.
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,  # no query string: may contain search terms
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            request_id_ctx.reset(token)


# Room for multipart boundaries and part headers on top of the file itself.
MULTIPART_OVERHEAD = 64 * 1024


class UploadSizeLimitMiddleware:
    """Rejects oversized uploads from their Content-Length *before* the body is read.

    Without this, the multipart parser spools the entire body to a temp file
    before the upload service gets to check its size. The service still enforces
    the exact limit while streaming (which also covers chunked requests that
    send no Content-Length).
    """

    def __init__(self, app: ASGIApp, *, paths: tuple[str, ...], max_body_size: int) -> None:
        self.app = app
        self.paths = paths
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] in self.paths:
            declared = Headers(scope=scope).get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_body_size + MULTIPART_OVERHEAD:
                limit_mb = self.max_body_size // (1024 * 1024)
                response = error_response(
                    413, "file_too_large", f"File is larger than the {limit_mb} MB limit.",
                    {"max_bytes": self.max_body_size},
                )  # fmt: skip
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
