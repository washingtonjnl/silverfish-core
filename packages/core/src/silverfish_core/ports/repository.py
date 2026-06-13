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
