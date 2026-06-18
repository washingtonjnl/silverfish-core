"""Tests for the import_book use case.

Written before the implementation (TDD). The service orchestrates the ports: it
extracts metadata, creates the book via the repository, then writes the file and
cover via storage. It performs no I/O itself, so we drive it with in-memory
fakes and assert the orchestration (what got created and where files landed).
"""

import dataclasses

import pytest

from silverfish_core.domain.models import Author, Book, BookFormat
from silverfish_core.ports.types import BookMeta, Page, SearchFilters, SortOrder
from silverfish_core.services.import_book import ImportBookService, UploadedFile


class FakeExtractor:
    def __init__(self, meta: BookMeta) -> None:
        self._meta = meta

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        return self._meta


class FakeRepository:
    def __init__(self) -> None:
        self.created: Book | None = None
        self._next_id = 7

    def create_book(self, book: Book) -> Book:
        # Echo back with an assigned id, like the real repository does.
        stored = dataclasses.replace(book, id=self._next_id)
        self.created = stored
        return stored

    def get_book(self, book_id: int) -> Book | None:
        return self.created

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        raise NotImplementedError

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        raise NotImplementedError

    def update_book(self, book: Book) -> Book:
        raise NotImplementedError

    def delete_book(self, book_id: int) -> None:
        raise NotImplementedError

    def cover_path(self, book_id: int) -> str | None:
        raise NotImplementedError

    def format_path(self, book_id: int, book_format: str) -> str | None:
        raise NotImplementedError

    def book_dir(self, book_id: int) -> str | None:
        raise NotImplementedError

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        raise NotImplementedError

    def remove_format(self, book_id: int, book_format: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.covers: dict[str, bytes] = {}

    def write_book_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def write_cover(self, book_dir: str, data: bytes) -> None:
        self.covers[book_dir] = data

    def read_book_file(self, path: str) -> bytes:
        return self.files[path]

    def move(self, old_path: str, new_path: str) -> None: ...
    def delete(self, path: str) -> None: ...


def _service(meta: BookMeta) -> tuple[ImportBookService, FakeRepository, FakeStorage]:
    repo = FakeRepository()
    storage = FakeStorage()
    service = ImportBookService(extractor=FakeExtractor(meta), repository=repo, storage=storage)
    return service, repo, storage


class TestImport:
    def test_creates_book_from_extracted_metadata(self) -> None:
        meta = BookMeta(title="Dune", extension=".epub", authors=("Frank Herbert",))
        service, repo, _ = _service(meta)

        book = service.import_book(UploadedFile(filename="x.epub", data=b"EPUBDATA"))

        assert book.id == 7
        assert repo.created is not None
        assert repo.created.title == "Dune"
        assert repo.created.authors == (Author(name="Frank Herbert", sort="Herbert, Frank"),)

    def test_writes_file_under_book_path(self) -> None:
        meta = BookMeta(title="Dune", extension=".epub", authors=("Frank Herbert",))
        service, _, storage = _service(meta)

        service.import_book(UploadedFile(filename="x.epub", data=b"EPUBDATA"))

        # File lands at "<author>/<title> (id)/<Title> - <Author>.epub".
        expected = "Frank Herbert/Dune (7)/Dune - Frank Herbert.epub"
        assert storage.files[expected] == b"EPUBDATA"

    def test_writes_cover_when_present(self) -> None:
        meta = BookMeta(
            title="Dune", extension=".epub", authors=("Frank Herbert",), cover=b"\xff\xd8jpeg"
        )
        service, _, storage = _service(meta)

        service.import_book(UploadedFile(filename="x.epub", data=b"E"))

        assert storage.covers["Frank Herbert/Dune (7)"] == b"\xff\xd8jpeg"

    def test_no_cover_written_when_absent(self) -> None:
        meta = BookMeta(title="Dune", extension=".epub", authors=("Frank Herbert",))
        service, _, storage = _service(meta)

        result = service.import_book(UploadedFile(filename="x.epub", data=b"E"))

        assert storage.covers == {}
        assert result.has_cover is False

    def test_records_format_with_size(self) -> None:
        meta = BookMeta(title="Dune", extension=".epub", authors=("Frank Herbert",))
        service, repo, _ = _service(meta)

        service.import_book(UploadedFile(filename="x.epub", data=b"12345"))

        assert repo.created is not None
        formats = repo.created.formats
        assert formats == (BookFormat(extension="EPUB", size_bytes=5, name="Dune - Frank Herbert"),)

    def test_rejects_disallowed_extension(self) -> None:
        meta = BookMeta(title="virus", extension=".exe")
        service, _, _ = _service(meta)

        with pytest.raises(ValueError, match=r"not allowed|extension"):
            service.import_book(
                UploadedFile(filename="virus.exe", data=b"MZ"), allowed_extensions=("epub",)
            )

    def test_unknown_author_defaults(self) -> None:
        meta = BookMeta(title="Anon Work", extension=".epub", authors=())
        service, repo, storage = _service(meta)

        service.import_book(UploadedFile(filename="x.epub", data=b"E"))

        assert repo.created is not None
        # With no author, the file path uses a sensible "Unknown" bucket.
        assert any("Unknown" in p for p in storage.files)
