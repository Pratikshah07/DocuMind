"""Shared fixtures.

Tests run against SQLite by default. Set TEST_DATABASE_URL to run the same
suite against PostgreSQL, e.g.
``TEST_DATABASE_URL=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_test``.
"""

import os
from collections.abc import Callable, Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

# Must be set before app modules read settings.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LOG_FORMAT", "console")

from app.api.deps import get_ocr_service  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.db.session import build_engine, get_db, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.ocr import OCRResult, OCRService, OCRUnavailableError, TesseractOCR  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402


def _tesseract_available() -> bool:
    try:
        TesseractOCR().check_available()
        return True
    except OCRUnavailableError:
        return False


requires_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed")


class FakeOCR(OCRService):
    """Deterministic OCR stand-in. Configure ``text``/``error``/``available``/``on_call`` per test."""

    name = "fake"

    def __init__(self) -> None:
        self.text = "FAKE OCR TEXT 123"
        self.confidence: float | None = 0.91
        self.error: Exception | None = None
        self.available = True
        self.on_call: Callable[[int], None] | None = None
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    def extract_text(self, image: np.ndarray, *, page_number: int) -> OCRResult:
        self.calls.append((page_number, image.shape))
        if self.on_call:
            self.on_call(page_number)
        if self.error:
            raise self.error
        return OCRResult(page_number=page_number, text=self.text, confidence=self.confidence)

    def check_available(self) -> str:
        if not self.available:
            raise OCRUnavailableError("fake engine disabled")
        return "fake 1.0"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = build_engine(os.environ["DATABASE_URL"])
    Base.metadata.drop_all(eng)  # a previous interrupted run may have left tables behind
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        # Keep tests independent: wipe rows, keep schema.
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def settings(tmp_path) -> Settings:
    return get_settings().model_copy(update={"storage_path": tmp_path / "storage"})


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.storage_path)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """What background jobs use to open their own sessions."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def fake_ocr() -> FakeOCR:
    return FakeOCR()


@pytest.fixture
def client(
    settings: Settings, db_session: Session, session_factory: sessionmaker[Session], fake_ocr: FakeOCR
) -> Iterator[TestClient]:
    """API client. Background tasks run before each call returns (TestClient semantics)."""
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_ocr_service] = lambda: fake_ocr
    with TestClient(app) as test_client:
        yield test_client


def pytest_make_parametrize_id(config: pytest.Config, val: object, argname: str) -> str | None:
    # Sample files are bytes; their repr as a test ID can exceed Windows' 32 KB env-var limit.
    if isinstance(val, bytes):
        return f"{argname}[{len(val)}B]"
    return None
