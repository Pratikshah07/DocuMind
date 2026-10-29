"""Storage interface.

Files are addressed by an opaque, server-generated *key* such as
``originals/<uuid>.pdf``. User-supplied filenames never become part of a key.
A future S3 backend implements the same interface with keys as object names.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import BinaryIO

# Top-level key prefixes. Keep in sync with the layout described in IMPLEMENTATION_PLAN.md.
ORIGINALS = "originals"
PROCESSED = "processed"
PREVIEWS = "previews"


class StorageError(Exception):
    """Base class for storage failures."""


class StorageObjectNotFoundError(StorageError):
    pass


class InvalidStorageKeyError(StorageError):
    pass


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: BinaryIO) -> int:
        """Write ``data`` (read from its current position to EOF) under ``key``. Returns bytes written.

        Overwrites an existing object. Writes must be atomic: a reader never sees a partial file.
        """

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Open an object for binary reading. Raises ``StorageObjectNotFoundError``."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an object. Returns False if it did not exist."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list_objects(self) -> Iterator[tuple[str, datetime]]:
        """Every stored key with its last-write time (UTC), for orphan cleanup."""

    def cleanup_temporary(self, older_than: datetime) -> int:
        """Remove abandoned partial writes older than ``older_than``. Returns how many."""
        return 0

    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Stream an object in chunks (for HTTP responses)."""
        with self.open(key) as handle:
            while chunk := handle.read(chunk_size):
                yield chunk
