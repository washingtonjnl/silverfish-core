"""Port: writing metadata into a book file.

Implemented by an adapter that rewrites EPUB metadata in pure Python and uses
``ebook-meta`` for MOBI/AZW3. Needed because e-readers read metadata from inside
the file, not from our database.
"""

from typing import Protocol, runtime_checkable

from silverfish_core.domain.models import Book


@runtime_checkable
class MetadataInjector(Protocol):
    """Embed a book's current metadata into the file on disk."""

    def inject(self, file_path: str, book: Book) -> None:
        """Write *book*'s metadata (title, authors, cover, ...) into *file_path*."""
        ...
