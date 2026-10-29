"""Application settings.

Every environment variable the backend reads is declared here. Nothing else in
the codebase should call ``os.environ`` directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "DocuMind API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- HTTP ---
    api_prefix: str = "/api"
    # Comma-separated in the environment, e.g. "http://localhost:5173,http://127.0.0.1:5173".
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # --- Database ---
    database_url: str = "postgresql+psycopg://documind:documind@127.0.0.1:5432/documind"
    database_echo: bool = False
    database_connect_timeout: int = 5  # seconds

    # --- Storage ---
    # "local": files under STORAGE_PATH (needs a persistent disk in production).
    # "database": file bytes in PostgreSQL (hosts with an ephemeral filesystem, e.g. Render free tier).
    storage_backend: Literal["local", "database"] = "local"
    storage_path: Path = BACKEND_DIR / "storage"
    max_upload_size: int = 15 * 1024 * 1024  # bytes

    # --- Public demo safeguards ---
    # When true, every request must carry an X-Workspace-Token header; each token is a private,
    # anonymous workspace (visitors never see each other's documents). When false (local
    # development), requests without the header share the "local" workspace.
    demo_mode: bool = False
    # Documents older than this are deleted automatically (0 = keep forever).
    retention_hours: int = Field(default=0, ge=0)
    # Uploads per client IP per hour (0 = unlimited) and documents per workspace (0 = unlimited).
    upload_rate_limit_per_hour: int = Field(default=0, ge=0)
    max_documents_per_workspace: int = Field(default=0, ge=0)
    # Documents processed at the same time (OCR is CPU/memory heavy).
    max_concurrent_jobs: int = Field(default=2, ge=1)
    # Trust X-Forwarded-For for the client IP (only behind a reverse proxy, e.g. Render).
    trust_proxy_headers: bool = False

    # --- Frontend ---
    # Directory with the built SPA (frontend/dist). When set, the API also serves the UI.
    static_dir: Path | None = None

    # --- Processing (PDF parsing, preprocessing, OCR) ---
    max_pages: int = 50  # documents with more pages are rejected (FAILED: too_many_pages)
    max_image_pixels: int = 40_000_000  # decompression-bomb guard for images and rendered pages
    # A PDF page whose text layer has fewer non-space characters than this is OCR'd instead.
    pdf_min_text_chars: int = 25
    ocr_render_dpi: int = 300
    preview_max_width: int = 1200  # px; previews are PNGs for the UI
    # Path to tesseract(.exe). Empty = PATH lookup, then the default Windows install location.
    tesseract_cmd: str = ""
    ocr_language: str = "eng"
    ocr_timeout_seconds: int = 60  # per page
    # Preprocessing steps (comma-separated, applied in order) before OCR.
    # Rendered PDF pages are already clean; camera images need more help.
    preprocess_pdf_steps: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["grayscale", "deskew"]
    )
    preprocess_image_steps: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["resize", "grayscale", "denoise", "contrast", "deskew", "threshold"]
    )
    # A QUEUED/RUNNING job older than this is treated as dead (e.g. server restarted mid-run).
    processing_stale_after_seconds: int = 15 * 60
    # Housekeeping loop (retention, stale-job recovery, orphaned-file sweep). 0 disables it.
    maintenance_interval_seconds: int = Field(default=15 * 60, ge=0)
    # At startup, fail every QUEUED/RUNNING job: jobs run in this process, so after a restart
    # none can still be running. Only correct with ONE app instance (see D47); turn off otherwise.
    recover_jobs_on_startup: bool = True

    # --- Extraction & validation (Phase 4) ---
    # How to read ambiguous numeric dates like 03/04/2025 (always flagged for review either way).
    date_order: Literal["DMY", "MDY"] = "DMY"
    # Confidence levels shown as High/Medium/Low. A required field below `confidence_review`
    # (the Medium threshold) sends the document to NEEDS_REVIEW.
    confidence_high: float = Field(default=0.85, ge=0, le=1)
    confidence_review: float = Field(default=0.60, ge=0, le=1)
    # Allowed rounding difference when checking subtotal + tax − discount = total, etc.
    amount_tolerance: float = Field(default=0.02, ge=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("preprocess_pdf_steps", "preprocess_image_steps", mode="before")
    @classmethod
    def _split_steps(cls, value: object) -> object:
        if isinstance(value, str):
            return [step.strip().lower() for step in value.split(",") if step.strip()]
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @field_validator("storage_path", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        # Relative paths are relative to backend/, not to whatever cwd uvicorn was started from.
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
