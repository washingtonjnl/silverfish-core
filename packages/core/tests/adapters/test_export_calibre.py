"""Tests for the CalibreExporter (TDD).

The exporter takes a snapshot of any library (read through a MetadataRepository
+ FileStorage) and writes it out as a real Calibre library directory: a
metadata.db plus ``Author/Title (id)/`` folders with the format files and
cover. The metadata.db is born from the ``calibredb`` binary (the faithful
schema midwife) and then populated through the Calibre repository, so the result
opens in Calibre desktop without any conversion.

``calibredb`` needs a real Calibre install and is invoked via a runner, so here
we inject a fake runner that materialises an empty Calibre metadata.db by
copying a committed template — letting us assert the full orchestration (books
added, files copied, cover written) without Calibre present.
"""

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.adapters.export_calibre import CalibreExporter, ExportError
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.domain.models import Author, Book, BookFormat
from silverfish_core.ports.types import Page, SortOrder

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "calibre_library" / "metadata.db"


def _empty_calibre_db(path: Path) -> None:
    """Make an empty Calibre metadata.db by copying the fixture and clearing it.

    Stands in for what ``calibredb`` does when it creates a fresh library: a
    valid Calibre schema (tables, triggers, functions) with no books.
    """
    shutil.copy(FIXTURE_DB, path)
    conn = sqlite3.connect(path)
    try:
        for table in ("books", "authors", "tags", "series", "data", "comments", "identifiers"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


class _FakeRunner:
    """Records calibredb invocations and materialises an empty library."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **kwargs: object) -> object:
        self.calls.append(argv)
        # Emulate calibredb creating the library: find --with-library DEST and
        # drop an empty metadata.db there.
        if "--with-library" in argv:
            dest = Path(argv[argv.index("--with-library") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            _empty_calibre_db(dest / "metadata.db")
        from silverfish_core.adapters.calibre_binaries import ProcessResult

        return ProcessResult(returncode=0, stdout="", stderr="")


class _SourceRepo:
    """A minimal in-memory source repository with two books."""

    def __init__(self) -> None:
        self._books = {
            1: Book(
                id=1,
                title="The Stand",
                sort="Stand, The",
                author_sort="King, Stephen",
                authors=(Author(name="Stephen King", sort="King, Stephen"),),
                formats=(
                    BookFormat(extension="EPUB", size_bytes=8, name="The Stand - Stephen King"),
                ),
                has_cover=True,
            ),
            2: Book(
                id=2,
                title="It",
                sort="It",
                author_sort="King, Stephen",
                authors=(Author(name="Stephen King", sort="King, Stephen"),),
            ),
        }

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        items = tuple(self._books.values())
        return Page(items=items, total=len(items), page=page, page_size=page_size)

    def get_book(self, book_id: int) -> Book | None:
        return self._books.get(book_id)

    def cover_path(self, book_id: int) -> str | None:
        return "The Stand/cover.jpg" if book_id == 1 else None

    def format_path(self, book_id: int, book_format: str) -> str | None:
        if book_id == 1 and book_format.upper() == "EPUB":
            return "The Stand/The Stand - Stephen King.epub"
        return None


class _SourceStorage:
    def read_book_file(self, path: str) -> bytes:
        return b"EPUBDATA" if path.endswith(".epub") else b"JPEGDATA"


@pytest.fixture
def runner() -> _FakeRunner:
    return _FakeRunner()


@pytest.fixture
def exporter(runner: _FakeRunner) -> Iterator[CalibreExporter]:
    exp = CalibreExporter(
        repository=_SourceRepo(),  # type: ignore[arg-type]
        storage=_SourceStorage(),  # type: ignore[arg-type]
        calibredb=Path("/fake/calibredb"),
        runner=runner,  # type: ignore[arg-type]
    )
    yield exp


class TestExport:
    def test_creates_metadata_db(self, exporter: CalibreExporter, tmp_path: Path) -> None:
        dest = tmp_path / "export"
        exporter.export(dest)
        assert (dest / "metadata.db").exists()

    def test_all_books_present_in_export(self, exporter: CalibreExporter, tmp_path: Path) -> None:
        dest = tmp_path / "export"
        result = exporter.export(dest)
        assert result.book_count == 2
        out = SqliteCalibreRepository(db_path=dest / "metadata.db")
        page = out.list_books(page=1, page_size=10, sort=SortOrder())
        assert {b.title for b in page.items} == {"The Stand", "It"}
        out.close()

    def test_format_file_is_copied(self, exporter: CalibreExporter, tmp_path: Path) -> None:
        dest = tmp_path / "export"
        exporter.export(dest)
        out = SqliteCalibreRepository(db_path=dest / "metadata.db")
        page = out.list_books(page=1, page_size=10, sort=SortOrder())
        stand = next(b for b in page.items if b.title == "The Stand")
        assert stand.id is not None
        rel = out.format_path(stand.id, "EPUB")
        out.close()
        assert rel is not None
        assert (dest / rel).read_bytes() == b"EPUBDATA"

    def test_cover_is_copied(self, exporter: CalibreExporter, tmp_path: Path) -> None:
        dest = tmp_path / "export"
        exporter.export(dest)
        out = SqliteCalibreRepository(db_path=dest / "metadata.db")
        page = out.list_books(page=1, page_size=10, sort=SortOrder())
        stand = next(b for b in page.items if b.title == "The Stand")
        assert stand.id is not None
        cover_rel = out.cover_path(stand.id)
        out.close()
        assert cover_rel is not None
        assert (dest / cover_rel).read_bytes() == b"JPEGDATA"

    def test_invokes_calibredb_with_destination(
        self, exporter: CalibreExporter, runner: _FakeRunner, tmp_path: Path
    ) -> None:
        dest = tmp_path / "export"
        exporter.export(dest)
        # The library was created via calibredb pointed at the destination.
        assert any("--with-library" in call for call in runner.calls)


class TestErrors:
    def test_export_into_nonempty_dir_raises(
        self, exporter: CalibreExporter, tmp_path: Path
    ) -> None:
        dest = tmp_path / "export"
        dest.mkdir()
        (dest / "something.txt").write_text("in the way")
        with pytest.raises(ExportError, match="empty"):
            exporter.export(dest)
