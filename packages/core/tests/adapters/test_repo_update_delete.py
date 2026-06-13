"""Tests for the write side: update_book and delete_book.

Written before the implementation (TDD). Updating recomputes sort/author_sort,
syncs M2M relationships (adding new, removing now-orphaned entities) and
recomputes books.path when the author or title changes. Deleting removes the row
(Calibre's delete trigger cascades to the link/data/comment tables). FS moves
are the service's job; here we verify the DB outcome and the reported path.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.domain.models import Author, Book, Series, Tag

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "calibre_library" / "metadata.db"


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteCalibreRepository]:
    db_copy = tmp_path / "metadata.db"
    shutil.copy(FIXTURE_DB, db_copy)
    repository = SqliteCalibreRepository(db_path=db_copy)
    yield repository
    repository.close()


def _count(repo: SqliteCalibreRepository, table: str, where: str = "") -> int:
    engine = create_engine(f"sqlite:///{repo.db_path}")
    clause = f" WHERE {where}" if where else ""
    with engine.connect() as conn:
        n = conn.execute(text(f"SELECT COUNT(*) FROM {table}{clause}")).scalar_one()
    engine.dispose()
    return int(n)


class TestUpdateFields:
    def test_updates_title_and_recomputes_sort(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(_with(book, title="The Lost Manuscript"))
        assert updated.title == "The Lost Manuscript"
        assert updated.sort == "Lost Manuscript, The"

    def test_updates_rating(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(_with(book, rating=4))
        assert updated.rating == 4

    def test_clears_rating(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(_with(book, rating=None))
        assert updated.rating is None


class TestUpdateRelationships:
    def test_adds_and_removes_tags(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(_with(book, tags=(Tag(name="newtag"),)))
        assert {t.name for t in updated.tags} == {"newtag"}

    def test_removes_orphaned_tag(self, repo: SqliteCalibreRepository) -> None:
        # Book 1 has "favorite"; if no other book uses it, it should be deleted.
        before = _count(repo, "tags", "lower(name)='favorite'")
        book = repo.get_book(1)
        assert book is not None
        repo.update_book(_with(book, tags=()))
        after = _count(repo, "tags", "lower(name)='favorite'")
        assert before == 1
        assert after == 0  # orphan removed

    def test_changes_author_and_recomputes_author_sort(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(
            _with(book, authors=(Author(name="Mary Shelley", sort=""),), author_sort="")
        )
        assert updated.author_sort == "Shelley, Mary"

    def test_changes_series(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        updated = repo.update_book(
            _with(book, series=Series(name="New Series", sort="New Series"), series_index=3.0)
        )
        assert updated.series is not None
        assert updated.series.name == "New Series"
        assert updated.series_index == 3.0


class TestPathRecompute:
    def test_path_changes_when_title_changes(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        old_dir = repo.book_dir(1)
        repo.update_book(_with(book, title="Renamed Title"))
        new_dir = repo.book_dir(1)
        assert old_dir != new_dir
        assert new_dir == "Jane Austen/Renamed Title (1)"

    def test_path_unchanged_when_only_rating_changes(self, repo: SqliteCalibreRepository) -> None:
        book = repo.get_book(1)
        assert book is not None
        old_dir = repo.book_dir(1)
        repo.update_book(_with(book, rating=2))
        assert repo.book_dir(1) == old_dir


class TestDelete:
    def test_delete_removes_book(self, repo: SqliteCalibreRepository) -> None:
        repo.delete_book(1)
        assert repo.get_book(1) is None

    def test_delete_cascades_links(self, repo: SqliteCalibreRepository) -> None:
        repo.delete_book(1)
        assert _count(repo, "books_authors_link", "book=1") == 0
        assert _count(repo, "books_tags_link", "book=1") == 0
        assert _count(repo, "data", "book=1") == 0

    def test_delete_missing_book_is_noop(self, repo: SqliteCalibreRepository) -> None:
        repo.delete_book(999999)  # must not raise


def _with(book: Book, **changes: object) -> Book:
    import dataclasses

    return dataclasses.replace(book, **changes)  # type: ignore[arg-type]
