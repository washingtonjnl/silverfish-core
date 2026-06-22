"""Tests for the send_to_ereader use case.

Written before the implementation (TDD). The service reads a book's format file,
builds a MIME email with it attached and sends it via the mailer. It enforces a
max attachment size and gives a clear error when the requested format is absent.
Driven with fakes.
"""

from email.message import EmailMessage

import pytest

from silverfish_core.domain.models import Author, Book
from silverfish_core.ports.types import Page, SearchFilters, SortOrder
from silverfish_core.services.send_to_ereader import SendToEreaderService


class FakeRepository:
    def __init__(self, book: Book) -> None:
        self.book = book

    def get_book(self, book_id: int) -> Book | None:
        return self.book if book_id == self.book.id else None

    def format_path(self, book_id: int, book_format: str) -> str | None:
        if book_id == self.book.id and book_format.upper() == "EPUB":
            return "Aldous Huxley/Brave New World (1)/Brave New World - Aldous Huxley.epub"
        return None

    # Unused.
    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        raise NotImplementedError

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        raise NotImplementedError

    def create_book(self, book: Book) -> Book:
        raise NotImplementedError

    def update_book(self, book: Book) -> Book:
        raise NotImplementedError

    def delete_book(self, book_id: int) -> None:
        raise NotImplementedError

    def cover_path(self, book_id: int) -> str | None:
        raise NotImplementedError

    def book_dir(self, book_id: int) -> str | None:
        raise NotImplementedError

    def add_format(self, book_id: int, extension: str, size_bytes: int, name: str) -> None:
        raise NotImplementedError

    def remove_format(self, book_id: int, book_format: str) -> None:
        raise NotImplementedError

    def set_has_cover(self, book_id: int, has_cover: bool) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class FakeStorage:
    def __init__(self, data: bytes = b"EPUBDATA") -> None:
        self.data = data

    def read_book_file(self, path: str) -> bytes:
        return self.data

    # Unused.
    def write_book_file(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def write_cover(self, book_dir: str, data: bytes) -> None:
        raise NotImplementedError

    def move(self, old_path: str, new_path: str) -> None:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class FakeMailer:
    def __init__(self) -> None:
        self.sent: EmailMessage | None = None

    def send(self, message: EmailMessage) -> None:
        self.sent = message

    def test(self, recipient: str) -> None:
        raise NotImplementedError


def _book() -> Book:
    return Book(
        id=1,
        title="Brave New World",
        sort="Brave New World",
        author_sort="Huxley, Aldous",
        authors=(Author(name="Aldous Huxley", sort="Huxley, Aldous"),),
    )


def _service(
    *, data: bytes = b"EPUBDATA", max_bytes: int = 25 * 1024 * 1024
) -> tuple[SendToEreaderService, FakeMailer]:
    mailer = FakeMailer()
    service = SendToEreaderService(
        repository=FakeRepository(_book()),
        storage=FakeStorage(data),
        mailer=mailer,
        max_attachment_bytes=max_bytes,
    )
    return service, mailer


class TestSend:
    def test_sends_email_with_attachment(self) -> None:
        service, mailer = _service()
        service.send(book_id=1, book_format="EPUB", to_email="me@kindle.com")
        assert mailer.sent is not None
        assert mailer.sent["To"] == "me@kindle.com"
        attachments = list(mailer.sent.iter_attachments())
        assert len(attachments) == 1

    def test_attachment_is_named_after_the_book(self) -> None:
        service, mailer = _service()
        service.send(book_id=1, book_format="EPUB", to_email="me@kindle.com")
        assert mailer.sent is not None
        attachment = next(mailer.sent.iter_attachments())
        assert attachment.get_filename() == "Brave New World - Aldous Huxley.epub"

    def test_subject_mentions_the_title(self) -> None:
        service, mailer = _service()
        service.send(book_id=1, book_format="EPUB", to_email="me@kindle.com")
        assert mailer.sent is not None
        assert "Brave New World" in str(mailer.sent["Subject"])


class TestErrors:
    def test_missing_book_raises(self) -> None:
        service, _ = _service()
        with pytest.raises(ValueError, match="not found"):
            service.send(book_id=999, book_format="EPUB", to_email="me@kindle.com")

    def test_missing_format_raises(self) -> None:
        service, _ = _service()
        with pytest.raises(ValueError, match="format"):
            service.send(book_id=1, book_format="MOBI", to_email="me@kindle.com")

    def test_oversize_attachment_raises(self) -> None:
        service, _ = _service(data=b"x" * 1000, max_bytes=500)
        with pytest.raises(ValueError, match=r"too large|size"):
            service.send(book_id=1, book_format="EPUB", to_email="me@kindle.com")
