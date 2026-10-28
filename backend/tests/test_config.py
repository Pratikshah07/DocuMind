from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, Settings


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test ,")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_relative_storage_path_resolves_under_backend(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", "data/files")
    assert Settings().storage_path == (BACKEND_DIR / "data/files").resolve()


def test_absolute_storage_path_is_kept(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    assert Settings().storage_path == tmp_path


def test_preprocessing_steps_parsed_from_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("PREPROCESS_IMAGE_STEPS", " Grayscale, threshold ,")
    assert Settings().preprocess_image_steps == ["grayscale", "threshold"]


def test_extraction_settings_are_validated(monkeypatch) -> None:
    monkeypatch.setenv("DATE_ORDER", "MDY")
    assert Settings().date_order == "MDY"
    monkeypatch.setenv("DATE_ORDER", "YMD")
    with pytest.raises(ValidationError):
        Settings()
