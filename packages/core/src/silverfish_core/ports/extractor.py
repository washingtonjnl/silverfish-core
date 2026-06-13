"""Port: extracting metadata from an uploaded file.

Implemented by a pure-Python adapter (EPUB via OPF, PDF via PyPDF, audio via
Mutagen, ...). No Calibre binary is involved in extraction.
"""

from typing import Protocol, runtime_checkable

from silverfish_core.ports.types import BookMeta


@runtime_checkable
class MetadataExtractor(Protocol):
    """Read metadata (and cover) out of a book file."""

    def extract(self, file_path: str, extension: str) -> BookMeta:
        """Return the metadata extracted from *file_path* of type *extension*."""
        ...
