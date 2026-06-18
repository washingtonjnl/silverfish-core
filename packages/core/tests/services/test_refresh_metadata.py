"""Tests for the refresh_metadata use case.

Written before the implementation (TDD). Re-extracts metadata from a chosen
format file and patches the book: fields the extraction produced replace the
current ones; fields it could not produce are left as they were (so a poor file
never erases existing metadata).
"""

import pytest

from silverfish_core.domain.models import Author, Book, Series, Tag
from silverfish_core.ports.types import BookMeta, Page, SearchFilters, SortOrder
from silverfish_core.services.refresh_metadata import RefreshMetadataService


class FakeExtractor:
    def __init__(self, meta: BookMeta) -> None:
        self._meta = meta

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        return self._meta


class FakeRepository:
    def __init__(self, book: Book) -> None:
        self.book = book

    def get_book(self, book_id: int) -> Book | None:
        return self.book if book_id == self.book.id else None

    def format_path(self, book_id: int, book_format: str) -> str | None:
        if book_id == self.book.id and book_format.upper() == "PDF":
            return "Author/Title (1)/Title - Author.pdf"
        return None

    # Unused by the refresh service.
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

    def close(self) -> None:
        raise NotImplementedError


class FakeStorage:
    def read_book_file(self, path: str) -> bytes:
        return b"FILE"

    # Unused by the refresh service.
    def write_book_file(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def write_cover(self, book_dir: str, data: bytes) -> None:
        raise NotImplementedError

    def move(self, old_path: str, new_path: str) -> None:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class FakeEditService:
    def __init__(self) -> None:
        self.edited: Book | None = None

    def edit_book(self, book: Book) -> Book:
        self.edited = book
        return book


def _service(*, book: Book, extracted: BookMeta) -> tuple[RefreshMetadataService, FakeEditService]:
    edit = FakeEditService()
    service = RefreshMetadataService(
        repository=FakeRepository(book),
        storage=FakeStorage(),
        extractor=FakeExtractor(extracted),
        edit_service=edit,
    )
    return service, edit


def _existing() -> Book:
    return Book(
        id=1,
        title="Old Title",
        sort="",
        author_sort="",
        authors=(Author(name="Old Author", sort="Author, Old"),),
        tags=(Tag(name="keep-me"),),
        series=Series(name="Old Series", sort="Old Series"),
        rating=7,
    )


class TestRefresh:
    def test_replaces_title_and_authors_from_extraction(self) -> None:
        extracted = BookMeta(title="New Title", extension=".pdf", authors=("New Author",))
        service, edit = _service(book=_existing(), extracted=extracted)
        result = service.refresh(book_id=1, source_format="PDF")
        assert result.title == "New Title"
        assert result.authors[0].name == "New Author"
        assert edit.edited is not None

    def test_keeps_existing_when_extraction_is_empty(self) -> None:
        # Extraction got only a title; existing tags/series/rating must remain.
        extracted = BookMeta(title="New Title", extension=".pdf", authors=())
        service, _ = _service(book=_existing(), extracted=extracted)
        result = service.refresh(book_id=1, source_format="PDF")
        assert result.title == "New Title"
        # Authors not extracted -> keep the old ones.
        assert result.authors[0].name == "Old Author"
        # Tags/series/rating not in extraction -> unchanged.
        assert {t.name for t in result.tags} == {"keep-me"}
        assert result.series is not None
        assert result.series.name == "Old Series"
        assert result.rating == 7

    def test_replaces_tags_and_series_when_extracted(self) -> None:
        extracted = BookMeta(
            title="T",
            extension=".pdf",
            authors=("A",),
            tags=("sci-fi",),
            series="New Saga",
            series_index=3.0,
        )
        service, _ = _service(book=_existing(), extracted=extracted)
        result = service.refresh(book_id=1, source_format="PDF")
        assert {t.name for t in result.tags} == {"sci-fi"}
        assert result.series is not None
        assert result.series.name == "New Saga"
        assert result.series_index == 3.0

    def test_missing_source_format_raises(self) -> None:
        service, _ = _service(book=_existing(), extracted=BookMeta(title="x", extension=".epub"))
        with pytest.raises(ValueError, match=r"format|not found"):
            service.refresh(book_id=1, source_format="MOBI")

    def test_missing_book_raises(self) -> None:
        service, _ = _service(book=_existing(), extracted=BookMeta(title="x", extension=".pdf"))
        with pytest.raises(ValueError, match="not found"):
            service.refresh(book_id=999, source_format="PDF")
