"""Tests for the native SQL repository (TDD).

``SqlNativeRepository`` is the standalone-mode implementation of
``MetadataRepository``: it CREATES and owns its schema (our neutral schema, not
Calibre's), assigns 64-bit Snowflake ids in Python, and computes sort/uuid/path
with the same domain rules — no SQLite triggers involved. It must run on SQLite
and (by using only portable SQLAlchemy) on Postgres; these tests exercise it on
an in-memory-style SQLite file.

The id generator is injected with a deterministic clock so created ids are
stable and ordered within a test.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.adapters.repo_sql_native import SqlNativeRepository
from silverfish_core.domain.models import Author, Book, BookFormat, Identifier, Series, Tag
from silverfish_core.ids import SnowflakeGenerator
from silverfish_core.ports import MetadataRepository
from silverfish_core.ports.types import SearchFilters, SortDirection, SortField, SortOrder

_EPOCH_MS = 1_704_067_200_000


class _Clock:
    def __init__(self) -> None:
        self._now = _EPOCH_MS + 1000

    def __call__(self) -> int:
        return self._now

    def tick(self) -> None:
        self._now += 1


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def repo(tmp_path: Path, clock: _Clock) -> Iterator[SqlNativeRepository]:
    generator = SnowflakeGenerator(machine_id=1, epoch_ms=_EPOCH_MS, clock=clock)
    repository = SqlNativeRepository(
        conn_string=f"sqlite:///{tmp_path / 'library.db'}",
        id_generator=generator,
    )
    yield repository
    repository.close()


def _new_book(**overrides: object) -> Book:
    defaults: dict[str, object] = {
        "id": None,
        "title": "Brave New World",
        "sort": "",
        "author_sort": "",
        "authors": (Author(name="Aldous Huxley", sort="Huxley, Aldous"),),
    }
    return Book(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestConformance:
    def test_is_a_metadata_repository(self, repo: SqlNativeRepository) -> None:
        assert isinstance(repo, MetadataRepository)


class TestCreate:
    def test_assigns_snowflake_id(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        # A Snowflake id is far larger than any autoincrement would produce.
        assert created.id > 1_000_000

    def test_persisted_book_is_readable(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        fetched = repo.get_book(created.id)
        assert fetched is not None
        assert fetched.title == "Brave New World"

    def test_computes_title_sort_in_python(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book(title="The Doors of Perception"))
        assert created.sort == "Doors of Perception, The"

    def test_computes_author_sort_when_blank(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(
            _new_book(authors=(Author(name="George Orwell", sort=""),), author_sort="")
        )
        assert created.author_sort == "Orwell, George"

    def test_sets_relative_path_with_id(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        assert repo.book_dir(created.id) == f"Aldous Huxley/Brave New World ({created.id})"

    def test_generates_uuid(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.uuid

    def test_reuses_existing_author(self, repo: SqlNativeRepository) -> None:
        repo.create_book(_new_book(authors=(Author(name="Shared Author", sort=""),)))
        repo.create_book(
            _new_book(title="Second", authors=(Author(name="Shared Author", sort=""),))
        )
        # Both books should reference the same single author row.
        page = repo.list_books(page=1, page_size=10, sort=SortOrder())
        authors = {a.name for book in page.items for a in book.authors}
        assert "Shared Author" in authors

    def test_persists_tags_series_rating(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(
            _new_book(
                tags=(Tag(name="dystopia"), Tag(name="classic")),
                series=Series(name="Huxley Collection", sort="Huxley Collection"),
                series_index=2.0,
                rating=8,
            )
        )
        assert created.id is not None
        fetched = repo.get_book(created.id)
        assert fetched is not None
        assert {t.name for t in fetched.tags} == {"dystopia", "classic"}
        assert fetched.series is not None
        assert fetched.series.name == "Huxley Collection"
        assert fetched.series_index == 2.0
        assert fetched.rating == 8

    def test_persists_formats_and_identifiers(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(
            _new_book(
                formats=(BookFormat(extension="EPUB", size_bytes=1234, name="Brave New World"),),
                identifiers=(Identifier(scheme="isbn", value="9780060850524"),),
            )
        )
        assert created.id is not None
        fetched = repo.get_book(created.id)
        assert fetched is not None
        assert "EPUB" in {f.extension for f in fetched.formats}
        assert ("isbn", "9780060850524") in {(i.scheme, i.value) for i in fetched.identifiers}


class TestGetBook:
    def test_returns_none_for_missing(self, repo: SqlNativeRepository) -> None:
        assert repo.get_book(999) is None


class TestListBooks:
    def test_lists_created_books(self, repo: SqlNativeRepository) -> None:
        repo.create_book(_new_book(title="Alpha"))
        repo.create_book(_new_book(title="Beta"))
        page = repo.list_books(page=1, page_size=10, sort=SortOrder())
        assert page.total == 2
        assert {b.title for b in page.items} == {"Alpha", "Beta"}

    def test_sorts_by_title(self, repo: SqlNativeRepository) -> None:
        repo.create_book(_new_book(title="Zebra"))
        repo.create_book(_new_book(title="Apple"))
        page = repo.list_books(
            page=1,
            page_size=10,
            sort=SortOrder(field=SortField.TITLE, direction=SortDirection.ASC),
        )
        assert [b.title for b in page.items] == ["Apple", "Zebra"]

    def test_paginates(self, repo: SqlNativeRepository) -> None:
        for i in range(5):
            repo.create_book(_new_book(title=f"Book {i}"))
        page = repo.list_books(page=2, page_size=2, sort=SortOrder())
        assert page.total == 5
        assert len(page.items) == 2
        assert page.page == 2


class TestSearch:
    def test_finds_by_title(self, repo: SqlNativeRepository) -> None:
        repo.create_book(_new_book(title="Findable Title"))
        repo.create_book(_new_book(title="Other"))
        page = repo.search("findable", filters=SearchFilters(), page=1, page_size=10)
        assert page.total == 1
        assert page.items[0].title == "Findable Title"

    def test_filters_by_tag(self, repo: SqlNativeRepository) -> None:
        repo.create_book(_new_book(title="Tagged", tags=(Tag(name="special"),)))
        repo.create_book(_new_book(title="Plain"))
        page = repo.search(
            "", filters=SearchFilters(include_tags=("special",)), page=1, page_size=10
        )
        assert {b.title for b in page.items} == {"Tagged"}


class TestUpdate:
    def test_updates_title_and_recomputes_sort(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book(title="Old Title"))
        assert created.id is not None
        changed = Book(
            id=created.id,
            title="The New Title",
            sort="",
            author_sort="",
            authors=(Author(name="Aldous Huxley", sort="Huxley, Aldous"),),
        )
        updated = repo.update_book(changed)
        assert updated.title == "The New Title"
        assert updated.sort == "New Title, The"

    def test_update_missing_book_raises(self, repo: SqlNativeRepository) -> None:
        ghost = Book(
            id=123456789,
            title="Ghost",
            sort="",
            author_sort="",
            authors=(Author(name="Nobody", sort="Nobody"),),
        )
        with pytest.raises(ValueError, match="exist"):
            repo.update_book(ghost)


class TestDelete:
    def test_deletes_book(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        repo.delete_book(created.id)
        assert repo.get_book(created.id) is None

    def test_delete_missing_is_noop(self, repo: SqlNativeRepository) -> None:
        repo.delete_book(999)  # must not raise


class TestFormats:
    def test_add_and_find_format_path(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        repo.add_format(created.id, extension="EPUB", size_bytes=10, name="Brave New World")
        path = repo.format_path(created.id, "epub")
        assert path is not None
        assert path.endswith("Brave New World.epub")

    def test_remove_format(self, repo: SqlNativeRepository) -> None:
        fmt = BookFormat(extension="EPUB", size_bytes=10, name="Brave New World")
        created = repo.create_book(_new_book(formats=(fmt,)))
        assert created.id is not None
        repo.remove_format(created.id, "EPUB")
        assert repo.format_path(created.id, "EPUB") is None

    def test_cover_path_none_without_cover(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book(has_cover=False))
        assert created.id is not None
        assert repo.cover_path(created.id) is None

    def test_cover_path_when_has_cover(self, repo: SqlNativeRepository) -> None:
        created = repo.create_book(_new_book(has_cover=True))
        assert created.id is not None
        path = repo.cover_path(created.id)
        assert path is not None
        assert path.endswith("cover.jpg")
