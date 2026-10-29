from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class StoredFile(Base):
    """File bytes for ``DatabaseStorage`` (STORAGE_BACKEND=database).

    Used on hosts without a persistent disk. Keyed by the same storage keys as
    ``LocalStorage`` (``originals/<uuid>.pdf``), so the rest of the app is unchanged.
    """

    __tablename__ = "stored_files"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
