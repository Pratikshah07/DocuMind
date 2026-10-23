"""Shared fixtures.

Tests run against SQLite by default. Set TEST_DATABASE_URL to run the same
suite against PostgreSQL, e.g.
``TEST_DATABASE_URL=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_test``.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

# Must be set before app modules read settings.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("LOG_FORMAT", "console")

from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.db.session import build_engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ["DATABASE_URL"]
    if url.startswith("sqlite") and ":memory:" in url:
        from sqlalchemy import create_engine

        # One shared connection so every session sees the same in-memory DB.
        eng = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        eng = build_engine(url)
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
def client(settings: Settings, db_session: Session) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
