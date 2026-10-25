"""Expected processing failures.

Each failure has a stable ``code`` (stored on the job, shown to API clients) and
a ``user_message`` (stored as ``documents.error_message``). Neither may contain
document content, file paths or library internals: the internal detail goes to
``processing_jobs.error_detail`` and the logs only.
"""


class ProcessingError(Exception):
    def __init__(self, code: str, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(f"{code}: {detail or user_message}")
        self.code = code
        self.user_message = user_message
        self.detail = detail


def corrupt_pdf(detail: str | None = None) -> ProcessingError:
    return ProcessingError("corrupt_pdf", "The PDF file is damaged and could not be read.", detail=detail)


def corrupt_image(detail: str | None = None) -> ProcessingError:
    return ProcessingError("corrupt_image", "The image file is damaged and could not be read.", detail=detail)
