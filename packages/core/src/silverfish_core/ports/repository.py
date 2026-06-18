"""Port: persistence of book metadata.

Implemented by adapters such as a SQLite-Calibre repository or a Postgres one.
The core never knows which; it only speaks this interface in terms of neutral
domain models.
"""

from typing import Protocol, runtime_checkable

from silverfish_core.domain.models import Book
from silverfish_core.ports.types import Page, SearchFilters, SortOrder


@runtime_checkable
class MetadataRepository(Protocol):
    """CRUD, listing and search over book metadata."""

    def get_book(self, book_id: int) -> Book | None:
        """Return the book with *book_id*, or ``None`` if it does not exist."""
        ...

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        """Return a paginated, sorted listing of books."""
        ...

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        """Return a paginated search result for *term* under *filters*."""
        ...

    def create_book(self, book: Book) -> Book:
        """Persist a new book and return it with its assigned id."""
        ...

    def update_book(self, book: Book) -> Book:
        """Persist changes to an existing book and return the updated book."""
        ...

    def delete_book(self, book_id: int) -> None:
        """Remove the book with *book_id*."""
        ...

    def cover_path(self, book_id: int) -> str | None:
        """Return the storage-relative path to the book's cover, or ``None``.

        The path is for internal use (read via ``FileStorage``); it is never
        exposed to API clients.
        """
        ...

    def format_path(self, book_id: int, book_format: str) -> str | None:
        """Return the storage-relative path to the book's file in *book_format*,
        or ``None`` if absent. Format match is case-insensitive.
        """
        ...

    def book_dir(self, book_id: int) -> str | None:
        """Return the storage-relative directory of a book, or ``None``.

        Used to relocate files when a rename changes the computed path.
        """
        ...

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        """Register a new format file for a book (a ``data`` row)."""
        ...

    def remove_format(self, book_id: int, book_format: str) -> None:
        """Remove a book's format record (a ``data`` row). Case-insensitive."""
        ...

    def close(self) -> None:
        """Release the repository's resources (e.g. the database engine)."""
        ...
