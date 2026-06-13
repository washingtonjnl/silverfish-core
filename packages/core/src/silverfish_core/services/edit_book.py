"""The edit_book and delete_book use cases.

Editing applies the metadata update in the repository and, when the recomputed
directory changes (an author or title rename), moves the book's folder via
storage so the files follow the DB. Deleting removes the row and the folder.
Pure orchestration over the repository and storage ports.
"""

from silverfish_core.domain.models import Book
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage


class EditBookService:
    """Edit or delete a library book, keeping files in sync with metadata."""

    def __init__(self, *, repository: MetadataRepository, storage: FileStorage) -> None:
        self._repository = repository
        self._storage = storage

    def edit_book(self, book: Book) -> Book:
        if book.id is None:
            msg = "edit_book requires a book with an id"
            raise ValueError(msg)
        if self._repository.get_book(book.id) is None:
            msg = f"Book {book.id} not found"
            raise ValueError(msg)

        old_dir = self._repository.book_dir(book.id)
        updated = self._repository.update_book(book)
        new_dir = self._repository.book_dir(book.id)

        # Relocate the folder only when the rename actually changed the path.
        if old_dir is not None and new_dir is not None and old_dir != new_dir:
            self._storage.move(old_dir, new_dir)

        return updated

    def delete_book(self, book_id: int) -> None:
        book_dir = self._repository.book_dir(book_id)
        if book_dir is None:
            return  # nothing to delete
        self._repository.delete_book(book_id)
        self._storage.delete(book_dir)
