"""Tests for the Google Drive ``FileStorage`` adapter (TDD).

The adapter maps library-relative paths to a real folder hierarchy in Drive
(``Author/`` > ``Title (id)/`` > file), under a configured root folder. Drive
addresses things by file id, not path, so the adapter resolves/creates each path
segment to a folder id (cached). A fake in-memory Drive client stands in for the
Google API, so these tests need no account or network.

Delivery: Drive is a product with its own UI, so a finished export is uploaded
and shared via a link Google serves (``shared_link``), not a presigned URL.
"""

from dataclasses import dataclass, field

import pytest

from silverfish_core.adapters.storage_gdrive import GDriveStorage
from silverfish_core.ports import FileStorage


@dataclass
class _Node:
    """A Drive entry: a folder (data is None) or a file (data is bytes)."""

    name: str
    parent_id: str | None
    data: bytes | None = None  # None => folder


@dataclass
class FakeDriveClient:
    """An in-memory stand-in for the Google Drive API used by the adapter.

    Models just what the adapter needs: a tree of folders/files addressed by id,
    with create/find/upload/download/delete/share. No network, no account.
    """

    root_id: str
    _nodes: dict[str, _Node] = field(default_factory=dict)
    _counter: int = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter}"

    def find_child(self, name: str, parent_id: str) -> str | None:
        for node_id, node in self._nodes.items():
            if node.parent_id == parent_id and node.name == name:
                return node_id
        return None

    def create_folder(self, name: str, parent_id: str) -> str:
        node_id = self._new_id()
        self._nodes[node_id] = _Node(name=name, parent_id=parent_id, data=None)
        return node_id

    def upload(self, name: str, parent_id: str, data: bytes) -> str:
        existing = self.find_child(name, parent_id)
        if existing is not None and self._nodes[existing].data is not None:
            self._nodes[existing].data = data
            return existing
        node_id = self._new_id()
        self._nodes[node_id] = _Node(name=name, parent_id=parent_id, data=data)
        return node_id

    def download(self, file_id: str) -> bytes:
        node = self._nodes[file_id]
        assert node.data is not None
        return node.data

    def list_children(self, parent_id: str) -> list[tuple[str, str, bool]]:
        # (id, name, is_folder) for each direct child.
        return [
            (nid, n.name, n.data is None)
            for nid, n in self._nodes.items()
            if n.parent_id == parent_id
        ]

    def delete(self, file_id: str) -> None:
        # Drive deletes a folder's contents with it; cascade to model that.
        for child_id, _, _ in self.list_children(file_id):
            self.delete(child_id)
        self._nodes.pop(file_id, None)

    def move(self, file_id: str, new_parent_id: str, new_name: str) -> None:
        node = self._nodes[file_id]
        node.parent_id = new_parent_id
        node.name = new_name

    def share_link(self, file_id: str, *, expires_in: int) -> str:
        node = self._nodes[file_id]
        return f"https://drive.google.com/file/{file_id}/{node.name}?ttl={expires_in}"


@pytest.fixture
def drive() -> FakeDriveClient:
    return FakeDriveClient(root_id="ROOT")


@pytest.fixture
def storage(drive: FakeDriveClient) -> GDriveStorage:
    return GDriveStorage(client=drive, root_folder_id="ROOT")


class TestConformance:
    def test_is_a_file_storage(self, storage: GDriveStorage) -> None:
        assert isinstance(storage, FileStorage)


class TestReadWrite:
    def test_write_then_read(self, storage: GDriveStorage) -> None:
        storage.write_book_file("Author/Title (1)/book.epub", b"EPUBDATA")
        assert storage.read_book_file("Author/Title (1)/book.epub") == b"EPUBDATA"

    def test_read_missing_raises(self, storage: GDriveStorage) -> None:
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("nope/missing.epub")

    def test_write_overwrites(self, storage: GDriveStorage) -> None:
        storage.write_book_file("a/b.epub", b"first")
        storage.write_book_file("a/b.epub", b"second")
        assert storage.read_book_file("a/b.epub") == b"second"

    def test_creates_a_real_folder_hierarchy(
        self, storage: GDriveStorage, drive: FakeDriveClient
    ) -> None:
        storage.write_book_file("Aldous Huxley/Brave New World (1)/book.epub", b"x")
        # The path became nested folders under the root, ending in the file.
        author = drive.find_child("Aldous Huxley", "ROOT")
        assert author is not None
        title = drive.find_child("Brave New World (1)", author)
        assert title is not None
        assert drive.find_child("book.epub", title) is not None


class TestCover:
    def test_write_cover(self, storage: GDriveStorage) -> None:
        storage.write_cover("Author/Title (1)", b"JPEGDATA")
        assert storage.read_book_file("Author/Title (1)/cover.jpg") == b"JPEGDATA"


class TestMove:
    def test_move_file(self, storage: GDriveStorage) -> None:
        storage.write_book_file("old/book.epub", b"DATA")
        storage.move("old/book.epub", "new/book.epub")
        assert storage.read_book_file("new/book.epub") == b"DATA"
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("old/book.epub")

    def test_move_directory(self, storage: GDriveStorage) -> None:
        storage.write_book_file("Author/Old (1)/book.epub", b"DATA")
        storage.write_book_file("Author/Old (1)/cover.jpg", b"COVER")
        storage.move("Author/Old (1)", "Author/New (1)")
        assert storage.read_book_file("Author/New (1)/book.epub") == b"DATA"
        assert storage.read_book_file("Author/New (1)/cover.jpg") == b"COVER"


class TestDelete:
    def test_delete_file(self, storage: GDriveStorage) -> None:
        storage.write_book_file("a/b.epub", b"DATA")
        storage.delete("a/b.epub")
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("a/b.epub")

    def test_delete_directory(self, storage: GDriveStorage) -> None:
        storage.write_book_file("dir (1)/book.epub", b"DATA")
        storage.write_book_file("dir (1)/cover.jpg", b"COVER")
        storage.delete("dir (1)")
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("dir (1)/book.epub")

    def test_delete_missing_is_noop(self, storage: GDriveStorage) -> None:
        storage.delete("not/there.epub")  # must not raise


class TestDownloadLink:
    def test_uploads_and_returns_a_share_link(self, storage: GDriveStorage) -> None:
        storage.write_book_file("exports/lib.zip", b"ZIPDATA")
        url = storage.download_link("exports/lib.zip", expires_in=600)
        assert url.startswith("http")
        assert "lib.zip" in url or "drive.google" in url


class TestTraversal:
    def test_absolute_path_rejected(self, storage: GDriveStorage) -> None:
        with pytest.raises(ValueError, match="bsolute"):
            storage.write_book_file("/etc/passwd", b"x")

    def test_parent_traversal_rejected(self, storage: GDriveStorage) -> None:
        with pytest.raises(ValueError, match=r"raversal|escape"):
            storage.read_book_file("../outside.epub")

    def test_empty_path_rejected(self, storage: GDriveStorage) -> None:
        with pytest.raises(ValueError, match="empty"):
            storage.read_book_file("")
