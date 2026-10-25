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
    storage_path: Path = BACKEND_DIR / "storage"
    max_upload_size: int = 15 * 1024 * 1024  # bytes

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

    @field_validator("storage_path", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        # Relative paths are relative to backend/, not to whatever cwd uvicorn was started from.
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
