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


@runtime_checkable
class PresignedDownload(Protocol):
    """Optional capability: hand out a direct, time-limited download URL.

    Backends that can serve an object directly (e.g. S3 presigned URLs) implement
    this so large downloads bypass the API server. Local disk does not; callers
    check ``isinstance(storage, PresignedDownload)`` and fall back to serving the
    file themselves.
    """

    def presigned_url(self, path: str, *, expires_in: int) -> str:
        """Return a URL that downloads the object at *path* for *expires_in* s."""
        ...
