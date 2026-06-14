"""The convert_book use case.

Reads the source format from storage, converts it to the target format via the
Converter, writes the result back to storage at the Calibre path, and registers
the new format in the repository. Spills to temp files because the converter
works on paths; temp files are always cleaned up.
"""

import tempfile
from collections.abc import Callable
from pathlib import Path

from silverfish_core.ports.converter import Converter
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage
from silverfish_core.ports.types import ConversionResult


class ConvertBookService:
    """Convert a book to a new format and register it."""

    def __init__(
        self,
        *,
        repository: MetadataRepository,
        storage: FileStorage,
        converter: Converter,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._converter = converter

    def convert_book(
        self,
        *,
        book_id: int,
        source_format: str,
        target_format: str,
        on_progress: Callable[[float], None] | None = None,
    ) -> ConversionResult:
        source_rel = self._repository.format_path(book_id, source_format)
        if source_rel is None:
            msg = f"Book {book_id} has no source format {source_format!r}"
            raise ValueError(msg)

        source_bytes = self._storage.read_book_file(source_rel)
        src_suffix = Path(source_rel).suffix
        out_suffix = f".{target_format.lower()}"

        with (
            tempfile.NamedTemporaryFile(suffix=src_suffix, delete=False) as src_tmp,
            tempfile.NamedTemporaryFile(suffix=out_suffix, delete=False) as out_tmp,
        ):
            src_path = Path(src_tmp.name)
            out_path = Path(out_tmp.name)
            src_path.write_bytes(source_bytes)

        try:
            result = self._converter.convert(str(src_path), str(out_path), on_progress=on_progress)
            if not result.ok:
                return result

            out_bytes = out_path.read_bytes()
            # New file shares the source's base name with the new extension.
            base_name = Path(source_rel).stem
            book_dir = self._repository.book_dir(book_id) or ""
            dest_rel = f"{book_dir}/{base_name}{out_suffix}"
            self._storage.write_book_file(dest_rel, out_bytes)
            self._repository.add_format(book_id, target_format.upper(), len(out_bytes), base_name)
            return result
        finally:
            src_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
