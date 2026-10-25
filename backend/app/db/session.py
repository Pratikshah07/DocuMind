"""Engine and session factory.

The engine is created lazily from settings so tests can point the app at a
different database before anything connects.
"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless this is on, per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(url: str, *, echo: bool = False, connect_timeout: int = 5) -> Engine:
    kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Background processing uses its own session on another thread.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # One shared connection, otherwise every connection gets its own empty database.
            kwargs["poolclass"] = StaticPool
    elif url.startswith("postgresql"):
        # Fail fast instead of hanging when the DB is down (e.g. a Docker port proxy with no backend).
        kwargs["connect_args"] = {"connect_timeout": connect_timeout}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return build_engine(
        settings.database_url,
        echo=settings.database_echo,
        connect_timeout=settings.database_connect_timeout,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session_factory() -> sessionmaker[Session]:
    """FastAPI dependency for code that outlives the request (background jobs open their own sessions)."""
    return get_sessionmaker()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def check_database(session: Session) -> None:
    """Raises if the database is unreachable."""
    session.execute(text("SELECT 1"))
