"""Tests for the write side of the SQLite-Calibre repository: create_book.

Written before the implementation (TDD). Creating a book must produce a row
indistinguishable from one Calibre would create: computed sort/author_sort,
relative path, reused (not duplicated) entities, and the rating on the DB's
0-10 scale. We verify by reading the book back through the same repository, and
by checking the entities were upserted (no duplicate authors/tags).
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.domain.models import Author, Book, BookFormat, Identifier, Series, Tag

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "calibre_library" / "metadata.db"


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteCalibreRepository]:
    db_copy = tmp_path / "metadata.db"
    shutil.copy(FIXTURE_DB, db_copy)
    repository = SqliteCalibreRepository(db_path=db_copy)
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
    merged = {**defaults, **overrides}
    return Book(**merged)  # type: ignore[arg-type]  # dynamic test helper


class TestCreateBasic:
    def test_returns_book_with_assigned_id(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        assert created.id > 0

    def test_persisted_book_is_readable(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        fetched = repo.get_book(created.id)
        assert fetched is not None
        assert fetched.title == "Brave New World"

    def test_computes_title_sort(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(_new_book(title="The Doors of Perception"))
        assert created.sort == "Doors of Perception, The"

    def test_computes_author_sort_when_blank(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(
            _new_book(authors=(Author(name="George Orwell", sort=""),), author_sort="")
        )
        assert created.author_sort == "Orwell, George"

    def test_sets_relative_path(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        fetched = repo.get_book(created.id)
        assert fetched is not None
        # Path is "Author/Title (id)".
        assert fetched_path(repo, created.id) == f"Aldous Huxley/Brave New World ({created.id})"

    def test_generates_uuid(self, repo: SqliteCalibreRepository) -> None:
        created = repo.create_book(_new_book())
        assert created.id is not None
        assert uuid_of(repo, created.id)


class TestEntities:
    def test_reuses_existing_author(self, repo: SqliteCalibreRepository) -> None:
        # The fixture already has "Jane Austen".
        before = author_count(repo, "jane austen")
        repo.create_book(_new_book(authors=(Author(name="Jane Austen", sort="Austen, Jane"),)))
        after = author_count(repo, "jane austen")
        assert before == 1
        assert after == 1  # reused, not duplicated

    def test_creates_new_author(self, repo: SqliteCalibreRepository) -> None:
        repo.create_book(_new_book(authors=(Author(name="Brand New Author", sort=""),)))
        assert author_count(repo, "brand new author") == 1

    def test_persists_tags_series_rating(self, repo: SqliteCalibreRepository) -> None:
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

    def test_persists_formats_and_identifiers(self, repo: SqliteCalibreRepository) -> None:
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


# --- small SQL helpers to inspect the raw DB --------------------------------


def fetched_path(repo: SqliteCalibreRepository, book_id: int) -> str | None:
    return _scalar(repo, "SELECT path FROM books WHERE id = :id", book_id)


def uuid_of(repo: SqliteCalibreRepository, book_id: int) -> str | None:
    return _scalar(repo, "SELECT uuid FROM books WHERE id = :id", book_id)


def author_count(repo: SqliteCalibreRepository, name_lower: str) -> int:
    engine = create_engine(f"sqlite:///{repo.db_path}")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM authors WHERE lower(name) = :n"), {"n": name_lower}
        ).scalar_one()
    engine.dispose()
    return int(row)


def _scalar(repo: SqliteCalibreRepository, sql: str, book_id: int) -> str | None:
    engine = create_engine(f"sqlite:///{repo.db_path}")
    with engine.connect() as conn:
        value = conn.execute(text(sql), {"id": book_id}).scalar_one_or_none()
    engine.dispose()
    return str(value) if value is not None else None
