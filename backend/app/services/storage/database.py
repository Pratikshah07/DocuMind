"""PostgreSQL-backed storage (STORAGE_BACKEND=database).

For hosts whose filesystem is wiped on restart (e.g. Render's free tier). Files are
capped by MAX_UPLOAD_SIZE and removed by retention/deletion, so table size stays
bounded for a demo. Each call uses its own short session, so file writes commit
independently of the caller's transaction, just like writing to disk.
"""

import io
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import StoredFile
from app.services.storage.base import StorageBackend, StorageObjectNotFoundError
from app.services.storage.local import validate_key


class DatabaseStorage(StorageBackend):
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def save(self, key: str, data: BinaryIO) -> int:
        validate_key(key)
        content = data.read()
        with self.session_factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                stmt = pg_insert(StoredFile).values(key=key, content=content, size_bytes=len(content))
                db.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[StoredFile.key],
                        set_={"content": stmt.excluded.content, "size_bytes": stmt.excluded.size_bytes},
                    )
                )
            else:  # SQLite (tests): merge = insert or replace by primary key
                db.merge(StoredFile(key=key, content=content, size_bytes=len(content)))
            db.commit()
        return len(content)

    def open(self, key: str) -> BinaryIO:
        validate_key(key)
        with self.session_factory() as db:
            content = db.scalar(select(StoredFile.content).where(StoredFile.key == key))
        if content is None:
            raise StorageObjectNotFoundError(key)
        return io.BytesIO(content)

    def delete(self, key: str) -> bool:
        validate_key(key)
        with self.session_factory() as db:
            deleted = db.execute(delete(StoredFile).where(StoredFile.key == key)).rowcount
            db.commit()
        return bool(deleted)

    def exists(self, key: str) -> bool:
        validate_key(key)
        with self.session_factory() as db:
            return db.scalar(select(StoredFile.key).where(StoredFile.key == key)) is not None

    def list_objects(self) -> Iterator[tuple[str, datetime]]:
        with self.session_factory() as db:
            rows = db.execute(select(StoredFile.key, StoredFile.created_at)).all()
        for key, created in rows:
            yield key, created if created.tzinfo else created.replace(tzinfo=UTC)
