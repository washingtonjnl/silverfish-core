"""Tests for the SQLite-Calibre repository adapter (read side).

Written before the implementation (TDD). These run against a real
``metadata.db`` produced by Calibre itself (tests/fixtures/calibre_library),
so the mapping is validated against the actual on-disk schema, not an idealised
one. Fixture contents (rating is the DB 0-10 scale):

    id  title             author_sort     series         tags                rating
    1   The Great Book    Austen, Jane    Classics #1    fiction, favorite   6
    2   A Tale of Code    Doe, John       -              tech, programming   10
    3   Dune              Herbert, Frank  Dune Saga #1   sci-fi              8
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.domain.models import Book
from silverfish_core.ports import MetadataRepository
from silverfish_core.ports.types import SearchFilters, SortDirection, SortField, SortOrder

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "calibre_library" / "metadata.db"


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteCalibreRepository]:
    # Work on a copy so tests never mutate the committed fixture.
    db_copy = tmp_path / "metadata.db"
    shutil.copy(FIXTURE_DB, db_copy)
    repository = SqliteCalibreRepository(db_path=db_copy)
    yield repository
    repository.close()


class TestConformance:
    def test_is_a_metadata_repository(self, repo: MetadataRepository) -> None:
        assert isinstance(repo, MetadataRepository)


class TestGetBook:
    def test_returns_none_for_missing(self, repo: MetadataRepository) -> None:
        assert repo.get_book(999) is None

    def test_maps_core_fields(self, repo: MetadataRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        assert book.id == 1
        assert book.title == "The Great Book"
        assert book.sort == "Great Book, The"
        assert book.author_sort == "Austen, Jane"

    def test_maps_authors(self, repo: MetadataRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        assert tuple(a.name for a in book.authors) == ("Jane Austen",)

    def test_maps_tags(self, repo: MetadataRepository) -> None:
        book = repo.get_book(2)
        assert book is not None
        assert {t.name for t in book.tags} == {"tech", "programming"}

    def test_maps_series_and_index(self, repo: MetadataRepository) -> None:
        book = repo.get_book(3)
        assert book is not None
        assert book.series is not None
        assert book.series.name == "Dune Saga"
        assert book.series_index == 1.0

    def test_book_without_series_has_none(self, repo: MetadataRepository) -> None:
        book = repo.get_book(2)
        assert book is not None
        assert book.series is None

    def test_maps_rating_directly_from_db_scale(self, repo: MetadataRepository) -> None:
        # DB stores 0-10; domain uses 0-10 — no conversion.
        assert repo.get_book(1).rating == 6  # type: ignore[union-attr]
        assert repo.get_book(2).rating == 10  # type: ignore[union-attr]
        assert repo.get_book(3).rating == 8  # type: ignore[union-attr]

    def test_maps_formats(self, repo: MetadataRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        assert "EPUB" in {f.extension for f in book.formats}

    def test_maps_languages(self, repo: MetadataRepository) -> None:
        book = repo.get_book(3)
        assert book is not None
        # Calibre stores ISO-639-2 ("eng"); we surface it as stored.
        assert "eng" in book.languages or "en" in book.languages


class TestListBooks:
    def test_lists_all_books(self, repo: MetadataRepository) -> None:
        page = repo.list_books(page=1, page_size=10, sort=SortOrder())
        assert page.total == 3
        assert len(page.items) == 3
        assert all(isinstance(b, Book) for b in page.items)

    def test_sorts_by_title_ascending(self, repo: MetadataRepository) -> None:
        page = repo.list_books(
            page=1,
            page_size=10,
            sort=SortOrder(field=SortField.TITLE, direction=SortDirection.ASC),
        )
        titles = [b.title for b in page.items]
        # Sorted by the Calibre sort key: "Dune", "Great Book, The", "Tale of Code, A"
        assert titles == ["Dune", "The Great Book", "A Tale of Code"]

    def test_pagination_splits_pages(self, repo: MetadataRepository) -> None:
        first = repo.list_books(page=1, page_size=2, sort=SortOrder())
        assert first.total == 3
        assert len(first.items) == 2
        assert first.has_next is True
        second = repo.list_books(page=2, page_size=2, sort=SortOrder())
        assert len(second.items) == 1
        assert second.has_next is False


class TestSearch:
    def test_finds_by_title_term(self, repo: MetadataRepository) -> None:
        page = repo.search("Dune", filters=SearchFilters(), page=1, page_size=10)
        assert {b.title for b in page.items} == {"Dune"}

    def test_finds_by_author_term(self, repo: MetadataRepository) -> None:
        page = repo.search("Austen", filters=SearchFilters(), page=1, page_size=10)
        assert {b.title for b in page.items} == {"The Great Book"}

    def test_filters_include_tag(self, repo: MetadataRepository) -> None:
        page = repo.search(
            "", filters=SearchFilters(include_tags=("sci-fi",)), page=1, page_size=10
        )
        assert {b.title for b in page.items} == {"Dune"}

    def test_filters_exclude_tag(self, repo: MetadataRepository) -> None:
        page = repo.search(
            "", filters=SearchFilters(exclude_tags=("sci-fi",)), page=1, page_size=10
        )
        titles = {b.title for b in page.items}
        assert "Dune" not in titles
        assert titles == {"The Great Book", "A Tale of Code"}

    def test_filters_rating_range(self, repo: MetadataRepository) -> None:
        page = repo.search("", filters=SearchFilters(rating_min=8), page=1, page_size=10)
        # ratings: Great Book 6, Tale 10, Dune 8  -> >=8 keeps Tale and Dune
        assert {b.title for b in page.items} == {"A Tale of Code", "Dune"}
