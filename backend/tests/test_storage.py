import io
from pathlib import Path

import pytest

from app.services.storage import InvalidStorageKeyError, LocalStorage, StorageObjectNotFoundError


def test_creates_layout_directories(tmp_path: Path) -> None:
    LocalStorage(tmp_path / "root")
    assert sorted(p.name for p in (tmp_path / "root").iterdir()) == ["originals", "previews", "processed"]


def test_save_open_exists_delete_roundtrip(storage: LocalStorage) -> None:
    key = "originals/abc.pdf"

    assert storage.save(key, io.BytesIO(b"hello")) == 5
    assert storage.exists(key)
    with storage.open(key) as handle:
        assert handle.read() == b"hello"
    assert b"".join(storage.iter_chunks(key, chunk_size=2)) == b"hello"

    assert storage.delete(key) is True
    assert not storage.exists(key)
    assert storage.delete(key) is False


def test_save_overwrites_and_leaves_no_temp_files(storage: LocalStorage) -> None:
    storage.save("originals/a.pdf", io.BytesIO(b"first"))
    storage.save("originals/a.pdf", io.BytesIO(b"second"))

    with storage.open("originals/a.pdf") as handle:
        assert handle.read() == b"second"
    assert [p.name for p in (storage.root / "originals").iterdir()] == ["a.pdf"]


def test_failed_save_leaves_nothing_behind(storage: LocalStorage) -> None:
    class Broken(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def readinto(self, buffer) -> int:  # type: ignore[override]
            raise OSError("disk went away")

    with pytest.raises(OSError):
        storage.save("originals/b.pdf", Broken())

    assert list((storage.root / "originals").iterdir()) == []


def test_open_missing_object_raises(storage: LocalStorage) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        storage.open("originals/missing.pdf")


@pytest.mark.parametrize(
    "key",
    [
        "../outside.pdf",
        "originals/../../outside.pdf",
        "originals/..",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "originals\\a.pdf",
        "originals/a b.pdf",
        "a.pdf",  # must have a prefix segment
        "",
    ],
)
def test_rejects_keys_that_could_escape_or_are_malformed(storage: LocalStorage, key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        storage.save(key, io.BytesIO(b"x"))
    with pytest.raises(InvalidStorageKeyError):
        storage.exists(key)
