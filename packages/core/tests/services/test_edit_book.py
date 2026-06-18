"""Tests for the edit_book and delete_book use cases.

Written before the implementation (TDD). Editing applies the DB update and, when
the computed directory changes (author/title rename), moves the book's folder
via storage. Deleting removes the DB row and the folder. Driven with fakes.
"""

import dataclasses

import pytest

from silverfish_core.domain.models import Author, Book
from silverfish_core.ports.types import Page, SearchFilters, SortOrder
from silverfish_core.services.edit_book import EditBookService


class FakeRepository:
    def __init__(self) -> None:
        self.books: dict[int, Book] = {}
        self.dirs: dict[int, str] = {}
        self.deleted: list[int] = []
        self.formats: dict[tuple[int, str], str] = {}
        self.removed_formats: list[tuple[int, str]] = []

    def add(self, book: Book, directory: str) -> None:
        assert book.id is not None
        self.books[book.id] = book
        self.dirs[book.id] = directory

    def get_book(self, book_id: int) -> Book | None:
        return self.books.get(book_id)

    def update_book(self, book: Book) -> Book:
        assert book.id is not None
        self.books[book.id] = book
        # Simulate the repo recomputing the directory from author/title.
        author = book.authors[0].name if book.authors else "Unknown"
        self.dirs[book.id] = f"{author}/{book.title} ({book.id})"
        return book

    def delete_book(self, book_id: int) -> None:
        self.deleted.append(book_id)
        self.books.pop(book_id, None)

    def book_dir(self, book_id: int) -> str | None:
        return self.dirs.get(book_id)

    def add_format_file(self, book_id: int, book_format: str, path: str) -> None:
        self.formats[(book_id, book_format.upper())] = path

    def format_path(self, book_id: int, book_format: str) -> str | None:
        return self.formats.get((book_id, book_format.upper()))

    def remove_format(self, book_id: int, book_format: str) -> None:
        self.removed_formats.append((book_id, book_format.upper()))
        self.formats.pop((book_id, book_format.upper()), None)

    # Unused by the edit service.
    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        raise NotImplementedError

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        raise NotImplementedError

    def create_book(self, book: Book) -> Book:
        raise NotImplementedError

    def cover_path(self, book_id: int) -> str | None:
        raise NotImplementedError

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class FakeStorage:
    def __init__(self) -> None:
        self.moves: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def move(self, old_path: str, new_path: str) -> None:
        self.moves.append((old_path, new_path))

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    # Unused here.
    def read_book_file(self, path: str) -> bytes:
        raise NotImplementedError

    def write_book_file(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def write_cover(self, book_dir: str, data: bytes) -> None:
        raise NotImplementedError


def _book(book_id: int = 1, *, title: str = "Old Title", author: str = "Jane Austen") -> Book:
    return Book(
        id=book_id,
        title=title,
        sort="",
        author_sort="",
        authors=(Author(name=author, sort=""),),
    )


def _service() -> tuple[EditBookService, FakeRepository, FakeStorage]:
    repo = FakeRepository()
    storage = FakeStorage()
    return EditBookService(repository=repo, storage=storage), repo, storage


class TestEdit:
    def test_updates_and_moves_when_title_changes(self) -> None:
        service, repo, storage = _service()
        repo.add(_book(1, title="Old Title"), "Jane Austen/Old Title (1)")

        service.edit_book(dataclasses.replace(_book(1), title="New Title"))

        assert storage.moves == [("Jane Austen/Old Title (1)", "Jane Austen/New Title (1)")]

    def test_no_move_when_directory_unchanged(self) -> None:
        service, repo, storage = _service()
        repo.add(_book(1, title="Same"), "Jane Austen/Same (1)")

        # Change only a non-path field (same title/author).
        service.edit_book(dataclasses.replace(_book(1, title="Same"), rating=5))

        assert storage.moves == []

    def test_returns_updated_book(self) -> None:
        service, repo, _ = _service()
        repo.add(_book(1, title="Old"), "Jane Austen/Old (1)")
        result = service.edit_book(dataclasses.replace(_book(1), title="Fresh"))
        assert result.title == "Fresh"

    def test_edit_missing_book_raises(self) -> None:
        service, _, _ = _service()
        with pytest.raises(ValueError, match=r"not found|does not exist"):
            service.edit_book(_book(999))


class TestDelete:
    def test_deletes_db_and_folder(self) -> None:
        service, repo, storage = _service()
        repo.add(_book(1), "Jane Austen/Old Title (1)")

        service.delete_book(1)

        assert repo.deleted == [1]
        assert storage.deleted == ["Jane Austen/Old Title (1)"]

    def test_delete_missing_book_is_noop(self) -> None:
        service, _, storage = _service()
        service.delete_book(999)  # must not raise
        assert storage.deleted == []


class TestDeleteFormat:
    def test_removes_file_and_data_row(self) -> None:
        service, repo, storage = _service()
        repo.add(_book(1), "Jane Austen/Old Title (1)")
        repo.add_format_file(1, "EPUB", "Jane Austen/Old Title (1)/Book.epub")

        removed = service.delete_format(1, "EPUB")

        assert removed is True
        assert repo.removed_formats == [(1, "EPUB")]
        assert storage.deleted == ["Jane Austen/Old Title (1)/Book.epub"]

    def test_returns_false_when_format_absent(self) -> None:
        service, repo, storage = _service()
        repo.add(_book(1), "Jane Austen/Old Title (1)")

        removed = service.delete_format(1, "MOBI")

        assert removed is False
        assert repo.removed_formats == []
        assert storage.deleted == []
