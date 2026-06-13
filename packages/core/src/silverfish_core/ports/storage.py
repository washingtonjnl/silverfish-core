"""Port: storage of book files and covers.

Implemented by adapters such as local disk, S3 or a user's Google Drive. Paths
are library-relative (e.g. ``"Author/Title (id)/Title - Author.epub"``); the
adapter resolves them to its own backend.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class FileStorage(Protocol):
    """Read/write book files and covers, and move/delete them on rename."""

    def read_book_file(self, path: str) -> bytes:
        """Return the bytes of the file at the library-relative *path*."""
        ...

    def write_book_file(self, path: str, data: bytes) -> None:
        """Write *data* to the library-relative *path*, creating parents."""
        ...

    def write_cover(self, book_dir: str, data: bytes) -> None:
        """Write ``cover.jpg`` into the library-relative *book_dir*."""
        ...

    def move(self, old_path: str, new_path: str) -> None:
        """Move a file or directory from *old_path* to *new_path*."""
        ...

    def delete(self, path: str) -> None:
        """Delete the file or directory at *path*."""
        ...
