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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("storage_path", mode="after")
    @classmethod
    def _resolve_storage(cls, value: Path) -> Path:
        # Relative paths are relative to backend/, not to whatever cwd uvicorn was started from.
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
