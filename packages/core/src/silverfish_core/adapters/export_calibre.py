"""Export any library to a real Calibre library directory (snapshot).

The exporter reads books through a ``MetadataRepository`` + ``FileStorage`` (so
it works regardless of where they actually live) and writes a Calibre library at
a destination directory: a ``metadata.db`` plus ``Author/Title (id)/`` folders
holding the format files and ``cover.jpg``. The metadata.db is created by the
``calibredb`` binary — the faithful schema midwife — and then populated through
``SqliteCalibreRepository``, which already knows how to write the Calibre schema.
The result opens in Calibre desktop with no further conversion.

This is a one-shot snapshot, not a live sync: ids are reassigned by the
destination, and a later change in the source does not propagate.
"""

from pathlib import Path

from silverfish_core.adapters.calibre_binaries import ProcessRunner
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.domain.models import Book
from silverfish_core.ports import FileStorage, MetadataRepository
from silverfish_core.ports.types import SortOrder

_EXPORT_PAGE_SIZE = 200


class ExportError(RuntimeError):
    """Raised when an export cannot proceed (bad destination, calibredb failure)."""


class CalibreExporter:
    """Snapshot a library into a Calibre-format directory."""

    def __init__(
        self,
        *,
        repository: MetadataRepository,
        storage: FileStorage,
        calibredb: Path,
        runner: ProcessRunner,
    ) -> None:
        self._source_repo = repository
        self._source_storage = storage
        self._calibredb = calibredb
        self._runner = runner

    def export(self, destination: Path) -> "ExportResult":
        """Write a Calibre library at *destination* and return a summary.

        *destination* must be empty (or not yet exist). Raises ``ExportError`` if
        it already holds files, or if creating the Calibre library fails.
        """
        self._check_destination(destination)
        destination.mkdir(parents=True, exist_ok=True)
        self._create_calibre_library(destination)

        dest_db = destination / "metadata.db"
        if not dest_db.exists():
            msg = "calibredb did not create a metadata.db at the destination."
            raise ExportError(msg)

        dest_repo = SqliteCalibreRepository(db_path=dest_db)
        dest_storage = LocalFileStorage(root=destination)
        try:
            count = self._copy_all_books(dest_repo, dest_storage)
        finally:
            dest_repo.close()
        return ExportResult(book_count=count, destination=destination)

    # --- steps --------------------------------------------------------------

    def _check_destination(self, destination: Path) -> None:
        if destination.exists() and any(destination.iterdir()):
            msg = f"Destination {destination} is not empty; export needs an empty directory."
            raise ExportError(msg)

    def _create_calibre_library(self, destination: Path) -> None:
        """Create an empty Calibre library at *destination* via ``calibredb``.

        A read-only ``list`` against a fresh directory makes Calibre materialise
        the library (metadata.db with the full schema). Runs as an argv list,
        never a shell.
        """
        result = self._runner.run(
            [str(self._calibredb), "--with-library", str(destination), "list"],
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            msg = f"calibredb could not create the Calibre library: {detail}"
            raise ExportError(msg)

    def _copy_all_books(self, dest_repo: SqliteCalibreRepository, dest_storage: FileStorage) -> int:
        count = 0
        for book in self._iter_source_books():
            created = dest_repo.create_book(book)
            self._copy_book_files(book, created, dest_repo, dest_storage)
            count += 1
        return count

    def _iter_source_books(self) -> list[Book]:
        """Read every source book, page by page."""
        books: list[Book] = []
        page = 1
        while True:
            result = self._source_repo.list_books(
                page=page, page_size=_EXPORT_PAGE_SIZE, sort=SortOrder()
            )
            books.extend(result.items)
            if not result.has_next:
                break
            page += 1
        return books

    def _copy_book_files(
        self,
        source_book: Book,
        created: Book,
        dest_repo: SqliteCalibreRepository,
        dest_storage: FileStorage,
    ) -> None:
        """Copy a book's format files and cover from source storage into the
        destination. ``create_book`` already registered the format rows; here we
        only move the bytes into the destination's book directory.
        """
        source_id = source_book.id
        new_id = created.id
        if source_id is None or new_id is None:  # pragma: no cover - ids are set
            return

        new_dir = dest_repo.book_dir(new_id)
        if new_dir is None:  # pragma: no cover - just-created book has a dir
            return

        for fmt in source_book.formats:
            rel = self._source_repo.format_path(source_id, fmt.extension)
            if rel is None:
                continue
            data = self._source_storage.read_book_file(rel)
            dest_storage.write_book_file(f"{new_dir}/{fmt.name}.{fmt.extension.lower()}", data)

        if source_book.has_cover:
            cover_rel = self._source_repo.cover_path(source_id)
            if cover_rel is not None:
                cover = self._source_storage.read_book_file(cover_rel)
                dest_storage.write_cover(new_dir, cover)


class ExportResult:
    """Summary of a completed export."""

    def __init__(self, *, book_count: int, destination: Path) -> None:
        self.book_count = book_count
        self.destination = destination
