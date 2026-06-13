"""Tests for the repository's file-location helpers.

Written before the implementation (TDD). The API never exposes filesystem
paths, but it needs to know where a book's cover and format files live to stream
them via storage. The repository resolves those library-relative paths from
``books.path`` and the ``data`` rows; they stay internal to the server.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "calibre_library" / "metadata.db"


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteCalibreRepository]:
    db_copy = tmp_path / "metadata.db"
    shutil.copy(FIXTURE_DB, db_copy)
    repository = SqliteCalibreRepository(db_path=db_copy)
    yield repository
    repository.close()


class TestCoverPath:
    def test_cover_path_for_book_with_cover(self, repo: SqliteCalibreRepository) -> None:
        # Fixture book 1 has has_cover=1 and path "Jane Austen/The Great Book (1)".
        path = repo.cover_path(1)
        assert path == "Jane Austen/The Great Book (1)/cover.jpg"

    def test_cover_path_none_for_missing_book(self, repo: SqliteCalibreRepository) -> None:
        assert repo.cover_path(999999) is None


class TestFormatPath:
    def test_format_path_resolves_data_row(self, repo: SqliteCalibreRepository) -> None:
        # Book 1 has an EPUB; the data name + book path give the file location.
        path = repo.format_path(1, "EPUB")
        assert path is not None
        assert path.startswith("Jane Austen/The Great Book (1)/")
        assert path.endswith(".epub")

    def test_format_path_is_case_insensitive(self, repo: SqliteCalibreRepository) -> None:
        assert repo.format_path(1, "epub") == repo.format_path(1, "EPUB")

    def test_format_path_none_for_missing_format(self, repo: SqliteCalibreRepository) -> None:
        assert repo.format_path(1, "MOBI") is None

    def test_format_path_none_for_missing_book(self, repo: SqliteCalibreRepository) -> None:
        assert repo.format_path(999999, "EPUB") is None
