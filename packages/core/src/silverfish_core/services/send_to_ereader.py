"""The send_to_ereader use case.

Reads a book's chosen format from storage, builds a MIME email with it attached
and sends it via the mailer (e.g. to a Kindle address). Enforces a maximum
attachment size and raises a clear error when the format is absent.
"""

import mimetypes
from email.message import EmailMessage
from pathlib import Path

from silverfish_core.ports.mailer import Mailer
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage

DEFAULT_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class SendToEreaderService:
    """Email a book's file to an e-reader address."""

    def __init__(
        self,
        *,
        repository: MetadataRepository,
        storage: FileStorage,
        mailer: Mailer,
        max_attachment_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._mailer = mailer
        self._max_attachment_bytes = max_attachment_bytes

    def send(self, *, book_id: int, book_format: str, to_email: str) -> None:
        book = self._repository.get_book(book_id)
        if book is None:
            msg = f"Book {book_id} not found"
            raise ValueError(msg)

        path = self._repository.format_path(book_id, book_format)
        if path is None:
            msg = f"Book {book_id} has no {book_format.upper()} format to send"
            raise ValueError(msg)

        data = self._storage.read_book_file(path)
        if len(data) > self._max_attachment_bytes:
            msg = (
                f"Attachment is too large to send "
                f"({len(data)} bytes > {self._max_attachment_bytes})"
            )
            raise ValueError(msg)

        message = self._build_message(book.title, to_email, filename=Path(path).name, data=data)
        self._mailer.send(message)

    def _build_message(
        self, title: str, to_email: str, *, filename: str, data: bytes
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = title
        message["To"] = to_email
        message.set_content(f"{title}\n\nSent from your Silverfish library.")

        content_type, _ = mimetypes.guess_type(filename)
        main_type, _, sub_type = (content_type or "application/octet-stream").partition("/")
        message.add_attachment(
            data, maintype=main_type, subtype=sub_type or "octet-stream", filename=filename
        )
        return message
