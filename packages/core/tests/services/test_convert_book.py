"""Tests for the convert_book use case.

Written before the implementation (TDD). The service reads the source format
from storage, converts it via the Converter to the target format, writes the
result back to storage at the Calibre path and registers the new format in the
repository. Driven with fakes; no real binary.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from silverfish_core.domain.models import Book
from silverfish_core.ports.types import ConversionResult, Page, SearchFilters, SortOrder
from silverfish_core.services.convert_book import ConvertBookService


class FakeRepository:
    def __init__(self) -> None:
        self.added: list[tuple[int, str, int, str]] = []
        self._book_dir = "Jane Austen/The Great Book (1)"

    def format_path(self, book_id: int, book_format: str) -> str | None:
        if book_id == 1 and book_format.upper() == "EPUB":
            return f"{self._book_dir}/The Great Book - Jane Austen.epub"
        return None

    def book_dir(self, book_id: int) -> str | None:
        return self._book_dir if book_id == 1 else None

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        self.added.append((book_id, extension, size_bytes, name))

    def remove_format(self, book_id: int, book_format: str) -> None:
        raise NotImplementedError

    # Unused by the convert service.
    def get_book(self, book_id: int) -> Book | None:
        raise NotImplementedError

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


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {
            "Jane Austen/The Great Book (1)/The Great Book - Jane Austen.epub": b"EPUBSOURCE"
        }

    def read_book_file(self, path: str) -> bytes:
        return self.files[path]

    def write_book_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    # Unused by the convert service.
    def write_cover(self, book_dir: str, data: bytes) -> None:
        raise NotImplementedError

    def move(self, old_path: str, new_path: str) -> None:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class FakeConverter:
    def __init__(self, *, ok: bool = True, error: str | None = None) -> None:
        self.ok = ok
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def convert(
        self,
        input_path: str,
        output_path: str,
        *,
        opf: bytes | None = None,
        cover: bytes | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> ConversionResult:
        self.calls.append((input_path, output_path))
        if self.ok:
            Path(output_path).write_bytes(b"CONVERTED")
            if on_progress:
                on_progress(1.0, "done")
        fmt = Path(output_path).suffix.lstrip(".").upper()
        return ConversionResult(ok=self.ok, output_format=fmt, error=self.error)


def _service(converter: FakeConverter) -> tuple[ConvertBookService, FakeRepository, FakeStorage]:
    repo = FakeRepository()
    storage = FakeStorage()
    return ConvertBookService(repository=repo, storage=storage, converter=converter), repo, storage


class TestConvert:
    def test_converts_and_registers_new_format(self) -> None:
        service, repo, storage = _service(FakeConverter(ok=True))

        result = service.convert_book(book_id=1, source_format="EPUB", target_format="PDF")

        assert result.ok is True
        # New file written under the book directory.
        out = "Jane Austen/The Great Book (1)/The Great Book - Jane Austen.pdf"
        assert storage.files[out] == b"CONVERTED"
        # Registered in the DB.
        assert repo.added == [(1, "PDF", len(b"CONVERTED"), "The Great Book - Jane Austen")]

    def test_reports_progress(self) -> None:
        service, _, _ = _service(FakeConverter(ok=True))
        seen: list[float] = []
        service.convert_book(
            book_id=1,
            source_format="EPUB",
            target_format="PDF",
            on_progress=lambda fraction, _message: seen.append(fraction),
        )
        assert 1.0 in seen

    def test_missing_source_format_raises(self) -> None:
        service, _, _ = _service(FakeConverter(ok=True))
        with pytest.raises(ValueError, match=r"source format|not found"):
            service.convert_book(book_id=1, source_format="MOBI", target_format="PDF")

    def test_conversion_failure_does_not_register(self) -> None:
        service, repo, _ = _service(FakeConverter(ok=False, error="boom"))
        result = service.convert_book(book_id=1, source_format="EPUB", target_format="PDF")
        assert result.ok is False
        assert repo.added == []
