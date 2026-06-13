"""Tests for the local-disk FileStorage adapter.

Written before the implementation (TDD). Security is a first-class concern here:
every library-relative path must be confined to the library root. Traversal
attempts (``..``, absolute paths, symlink escapes) must be rejected, never
silently resolved outside the root.
"""

from pathlib import Path

import pytest

from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.ports import FileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


class TestConformance:
    def test_is_a_file_storage(self, storage: LocalFileStorage) -> None:
        assert isinstance(storage, FileStorage)


class TestReadWrite:
    def test_write_then_read_roundtrip(self, storage: LocalFileStorage) -> None:
        storage.write_book_file("Author/Title (1)/Title - Author.epub", b"hello")
        assert storage.read_book_file("Author/Title (1)/Title - Author.epub") == b"hello"

    def test_write_creates_parent_directories(
        self, storage: LocalFileStorage, tmp_path: Path
    ) -> None:
        storage.write_book_file("a/b/c/book.epub", b"x")
        assert (tmp_path / "a" / "b" / "c" / "book.epub").read_bytes() == b"x"

    def test_write_cover_writes_cover_jpg(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        storage.write_cover("Author/Title (1)", b"\xff\xd8\xff")
        assert (tmp_path / "Author" / "Title (1)" / "cover.jpg").read_bytes() == b"\xff\xd8\xff"

    def test_read_missing_file_raises(self, storage: LocalFileStorage) -> None:
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("nope/missing.epub")


class TestMoveAndDelete:
    def test_move_file(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        storage.write_book_file("old/book.epub", b"data")
        storage.move("old/book.epub", "new/book.epub")
        assert not (tmp_path / "old" / "book.epub").exists()
        assert (tmp_path / "new" / "book.epub").read_bytes() == b"data"

    def test_move_directory(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        storage.write_book_file("Old Author/Title (1)/book.epub", b"d")
        storage.move("Old Author/Title (1)", "New Author/Title (1)")
        assert (tmp_path / "New Author" / "Title (1)" / "book.epub").exists()

    def test_delete_file(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        storage.write_book_file("x/book.epub", b"d")
        storage.delete("x/book.epub")
        assert not (tmp_path / "x" / "book.epub").exists()

    def test_delete_directory(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        storage.write_book_file("x/y/book.epub", b"d")
        storage.delete("x/y")
        assert not (tmp_path / "x" / "y").exists()


class TestPathTraversalSecurity:
    @pytest.mark.parametrize(
        "evil",
        [
            "../escape.txt",
            "../../etc/passwd",
            "a/../../escape.txt",
            "/etc/passwd",
            "a/b/../../../escape.txt",
        ],
    )
    def test_read_rejects_traversal(self, storage: LocalFileStorage, evil: str) -> None:
        with pytest.raises(ValueError, match=r"outside|invalid|traversal"):
            storage.read_book_file(evil)

    @pytest.mark.parametrize(
        "evil",
        [
            "../escape.txt",
            "../../etc/passwd",
            "/etc/passwd",
            "a/../../escape.txt",
        ],
    )
    def test_write_rejects_traversal(self, storage: LocalFileStorage, evil: str) -> None:
        with pytest.raises(ValueError, match=r"outside|invalid|traversal"):
            storage.write_book_file(evil, b"pwned")

    def test_write_does_not_create_file_outside_root(
        self, storage: LocalFileStorage, tmp_path: Path
    ) -> None:
        target = tmp_path.parent / "escape.txt"
        with pytest.raises(ValueError, match=r"outside|invalid|traversal"):
            storage.write_book_file("../escape.txt", b"pwned")
        assert not target.exists()

    def test_move_rejects_traversal_on_either_side(self, storage: LocalFileStorage) -> None:
        storage.write_book_file("ok/book.epub", b"d")
        with pytest.raises(ValueError, match=r"outside|invalid|traversal"):
            storage.move("ok/book.epub", "../escape.epub")
        with pytest.raises(ValueError, match=r"outside|invalid|traversal"):
            storage.move("../escape.epub", "ok/book2.epub")

    def test_empty_path_rejected(self, storage: LocalFileStorage) -> None:
        with pytest.raises(ValueError, match=r"empty|invalid"):
            storage.read_book_file("")
