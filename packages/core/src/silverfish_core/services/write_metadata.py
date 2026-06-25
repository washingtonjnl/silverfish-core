"""The write_metadata use case.

Embeds a book's current database metadata back into one of its format files, so
an e-reader (which reads metadata from inside the file, not from our database)
shows what the library shows. This is the inverse of refresh_metadata.

One call handles one format: the API enqueues one job per format the book has,
so each format's progress is tracked independently and a failure on one file
never blocks the others. The injector rewrites a path, so bytes are spilled to a
temp file, injected in place, then written back to storage; the temp file is
always cleaned up.
"""

from collections.abc import Callable
from pathlib import Path

from silverfish_core.ports.injector import MetadataInjector
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage
from silverfish_core.services.spill import spill_named


class WriteMetadataService:
    """Write a book's metadata into one of its format files."""

    def __init__(
        self,
        *,
        repository: MetadataRepository,
        storage: FileStorage,
        injector: MetadataInjector,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._injector = injector

    def write_format(
        self,
        *,
        book_id: int,
        book_format: str,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> None:
        book = self._repository.get_book(book_id)
        if book is None:
            msg = f"Book {book_id} not found"
            raise ValueError(msg)

        rel_path = self._repository.format_path(book_id, book_format)
        if rel_path is None:
            msg = f"Book {book_id} has no format {book_format!r}"
            raise ValueError(msg)

        if on_progress is not None:
            on_progress(0.0, f"Writing {book_format.upper()} metadata")

        data = self._storage.read_book_file(rel_path)
        suffix = Path(rel_path).suffix
        with spill_named(data, base_name=book.title, suffix=suffix) as tmp_path:
            self._injector.inject(str(tmp_path), book)
            updated = tmp_path.read_bytes()

        self._storage.write_book_file(rel_path, updated)
        if on_progress is not None:
            on_progress(1.0, "Done")
