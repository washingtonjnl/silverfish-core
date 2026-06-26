"""Tests for the write_metadata use case.

Written before the implementation (TDD). The service reads one of a book's
format files from storage, embeds the book's current database metadata into it
via the MetadataInjector, and writes the modified bytes back to the same path.
One call handles one format; the caller enqueues one job per format. Driven with
fakes; no real binary.
"""

from pathlib import Path

import pytest

from silverfish_core.domain.models import Author, Book, BookFormat
from silverfish_core.ports.types import Page, SearchFilters, SortOrder
from silverfish_core.services.write_metadata import WriteMetadataService


def _book() -> Book:
    return Book(
        id=1,
        title="The Great Book",
        sort="Great Book, The",
        author_sort="Austen, Jane",
        authors=(Author(name="Jane Austen", sort="Austen, Jane"),),
        formats=(
            BookFormat(extension="EPUB", size_bytes=10, name="The Great Book - Jane Austen"),
            BookFormat(extension="PDF", size_bytes=20, name="The Great Book - Jane Austen"),
        ),
    )


class FakeRepository:
    def __init__(self, book: Book | None) -> None:
        self._book = book
        self._dir = "Jane Austen/The Great Book (1)"

    def get_book(self, book_id: int) -> Book | None:
        return self._book if self._book and self._book.id == book_id else None

    def format_path(self, book_id: int, book_format: str) -> str | None:
        if self._book is None or book_id != self._book.id:
            return None
        fmt = book_format.upper()
        if fmt not in {f.extension for f in self._book.formats}:
            return None
        return f"{self._dir}/The Great Book - Jane Austen.{fmt.lower()}"

    # Unused by the write-metadata service.
    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        raise NotImplementedError

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        raise NotImplementedError

    def create_book(self, book: Book) -> Book:
        raise NotImplementedError

    def update_book(self, book: Book) -> Book:
        raise NotImplementedError

    def delete_book(self, book_id: int) -> None:
        raise NotImplementedError

    def cover_path(self, book_id: int) -> str | None:
        raise NotImplementedError

    def book_dir(self, book_id: int) -> str | None:
        raise NotImplementedError

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        raise NotImplementedError

    def remove_format(self, book_id: int, book_format: str) -> None:
        raise NotImplementedError

    def set_has_cover(self, book_id: int, has_cover: bool) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class FakeStorage:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.writes: list[tuple[str, bytes]] = []

    def read_book_file(self, path: str) -> bytes:
        self.reads.append(path)
        return b"ORIGINAL-BYTES"

    def write_book_file(self, path: str, data: bytes) -> None:
        self.writes.append((path, data))

    # Unused by the write-metadata service.
    def write_cover(self, book_dir: str, data: bytes) -> None:
        raise NotImplementedError

    def move(self, old_path: str, new_path: str) -> None:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class FakeInjector:
    def __init__(self, *, mutate_to: bytes = b"NEW-BYTES", fail: bool = False) -> None:
        self.calls: list[tuple[str, Book]] = []
        self._mutate_to = mutate_to
        self._fail = fail

    def inject(self, file_path: str, book: Book) -> None:
        self.calls.append((file_path, book))
        if self._fail:
            msg = "injection failed"
            raise RuntimeError(msg)
        # Simulate ebook-meta rewriting the file in place.
        Path(file_path).write_bytes(self._mutate_to)


def _service(
    *, book: Book | None = None, injector: FakeInjector | None = None
) -> tuple[WriteMetadataService, FakeStorage, FakeInjector]:
    storage = FakeStorage()
    inj = injector or FakeInjector()
    service = WriteMetadataService(
        repository=FakeRepository(book if book is not None else _book()),
        storage=storage,
        injector=inj,
    )
    return service, storage, inj


class TestWriteFormat:
    def test_reads_the_requested_format_from_storage(self) -> None:
        service, storage, _ = _service()
        service.write_format(book_id=1, book_format="EPUB")
        assert storage.reads == ["Jane Austen/The Great Book (1)/The Great Book - Jane Austen.epub"]

    def test_injects_book_metadata(self) -> None:
        service, _, injector = _service()
        service.write_format(book_id=1, book_format="EPUB")
        assert len(injector.calls) == 1
        _, book = injector.calls[0]
        assert book.title == "The Great Book"

    def test_writes_modified_bytes_back_to_the_same_path(self) -> None:
        service, storage, _ = _service()
        service.write_format(book_id=1, book_format="EPUB")
        assert len(storage.writes) == 1
        path, data = storage.writes[0]
        assert path == "Jane Austen/The Great Book (1)/The Great Book - Jane Austen.epub"
        assert data == b"NEW-BYTES"

    def test_reports_progress_complete(self) -> None:
        service, _, _ = _service()
        seen: list[float] = []
        service.write_format(book_id=1, book_format="PDF", on_progress=lambda f, _m: seen.append(f))
        assert seen and seen[-1] == 1.0

    def test_format_is_case_insensitive(self) -> None:
        service, storage, _ = _service()
        service.write_format(book_id=1, book_format="epub")
        assert storage.writes


class TestErrors:
    def test_missing_book_raises(self) -> None:
        service, _, _ = _service(book=Book(id=99, title="x", sort="x", author_sort="x"))
        with pytest.raises(ValueError, match="not found"):
            service.write_format(book_id=1, book_format="EPUB")

    def test_missing_format_raises(self) -> None:
        service, _, _ = _service()
        with pytest.raises(ValueError, match="MOBI"):
            service.write_format(book_id=1, book_format="MOBI")

    def test_injector_failure_propagates_and_skips_write(self) -> None:
        service, storage, _ = _service(injector=FakeInjector(fail=True))
        with pytest.raises(RuntimeError, match="injection failed"):
            service.write_format(book_id=1, book_format="EPUB")
        assert storage.writes == []
