"""Engine and session factory.

The engine is created lazily from settings so tests can point the app at a
different database before anything connects.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(url: str, *, echo: bool = False, connect_timeout: int = 5) -> Engine:
    kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Background processing uses its own session on another thread.
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql"):
        # Fail fast instead of hanging when the DB is down (e.g. a Docker port proxy with no backend).
        kwargs["connect_args"] = {"connect_timeout": connect_timeout}
    return create_engine(url, **kwargs)


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
