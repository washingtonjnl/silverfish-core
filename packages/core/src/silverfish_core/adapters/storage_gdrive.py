"""Google Drive implementation of the ``FileStorage`` port.

Maps library-relative paths to a real folder hierarchy under a configured root
folder (``Author/`` > ``Title (id)/`` > file), so the library is readable in the
user's Drive. Drive addresses things by file id, not path, so each path segment
is resolved (or created) to a folder id, cached to avoid repeat lookups.

The adapter talks to a small ``DriveClient`` protocol rather than the verbose
Google API directly — the concrete client (``GoogleDriveClient``) wraps
``googleapiclient``; tests use an in-memory fake. Credentials come pre-resolved
in that client (the OAuth consent flow that obtains them is the product's job).

Delivery: Drive is a product with its own UI, so a finished export is uploaded
and shared via a link Google serves (``shared_link``), not a presigned URL.
``google-api-python-client`` is the optional ``gdrive`` extra.
"""

from typing import Protocol, runtime_checkable

_PARENT = ".."


@runtime_checkable
class DriveClient(Protocol):
    """The slice of the Drive API the storage adapter needs."""

    def find_child(self, name: str, parent_id: str) -> str | None:
        """Return the id of a direct child named *name* under *parent_id*."""
        ...

    def create_folder(self, name: str, parent_id: str) -> str:
        """Create a folder named *name* under *parent_id*; return its id."""
        ...

    def upload(self, name: str, parent_id: str, data: bytes) -> str:
        """Upload (or overwrite) a file named *name* under *parent_id*."""
        ...

    def download(self, file_id: str) -> bytes:
        """Return the bytes of the file with *file_id*."""
        ...

    def list_children(self, parent_id: str) -> list[tuple[str, str, bool]]:
        """Return ``(id, name, is_folder)`` for each direct child of *parent_id*."""
        ...

    def delete(self, file_id: str) -> None:
        """Delete the file or folder with *file_id*."""
        ...

    def move(self, file_id: str, new_parent_id: str, new_name: str) -> None:
        """Re-parent and/or rename the entry with *file_id*."""
        ...

    def share_link(self, file_id: str, *, expires_in: int) -> str:
        """Return a shareable URL for *file_id* (Google serves the download)."""
        ...


class GDriveStorage:
    """Store book files and covers as a folder tree in Google Drive."""

    def __init__(self, *, client: DriveClient, root_folder_id: str) -> None:
        self._client = client
        self._root = root_folder_id
        # Cache of "parent_id/name" -> folder id, so a deep path is resolved once.
        self._folder_cache: dict[tuple[str, str], str] = {}

    # --- path handling ------------------------------------------------------

    def _segments(self, path: str) -> list[str]:
        """Split a library-relative *path* into safe segments.

        Rejects empty paths, absolute paths and ``..`` traversal.
        """
        if not path or not path.strip():
            msg = "Path must not be empty"
            raise ValueError(msg)
        if path.startswith("/"):
            msg = f"Absolute paths are invalid: {path!r}"
            raise ValueError(msg)
        parts = [p for p in path.split("/") if p not in ("", ".")]
        if _PARENT in parts:
            msg = f"Path escapes the storage root (traversal): {path!r}"
            raise ValueError(msg)
        return parts

    def _resolve_folder(self, segments: list[str], *, create: bool) -> str | None:
        """Resolve a chain of folder names to the deepest folder id.

        With *create*, missing folders are made; without it, a missing folder
        yields ``None``.
        """
        parent = self._root
        for name in segments:
            cache_key = (parent, name)
            cached = self._folder_cache.get(cache_key)
            if cached is not None:
                parent = cached
                continue
            child = self._client.find_child(name, parent)
            if child is None:
                if not create:
                    return None
                child = self._client.create_folder(name, parent)
            self._folder_cache[cache_key] = child
            parent = child
        return parent

    def _ensure_folder(self, segments: list[str]) -> str:
        """Resolve a folder chain, creating any missing folders. Always returns
        a folder id (``_resolve_folder`` with ``create=True`` never yields None).
        """
        folder_id = self._resolve_folder(segments, create=True)
        if folder_id is None:  # pragma: no cover - create=True guarantees an id
            msg = "Failed to create the Drive folder hierarchy"
            raise RuntimeError(msg)
        return folder_id

    def _resolve_file(self, path: str) -> tuple[str, str] | None:
        """Return ``(parent_folder_id, file_id)`` for a *file* at *path*.

        ``None`` if the path does not resolve to a file (missing, or a folder).
        """
        *folders, filename = self._segments(path)
        parent = self._resolve_folder(folders, create=False)
        if parent is None:
            return None
        for child_id, name, is_folder in self._client.list_children(parent):
            if name == filename and not is_folder:
                return parent, child_id
        return None

    # --- FileStorage --------------------------------------------------------

    def read_book_file(self, path: str) -> bytes:
        resolved = self._resolve_file(path)
        if resolved is None:
            raise FileNotFoundError(path)
        return self._client.download(resolved[1])

    def write_book_file(self, path: str, data: bytes) -> None:
        *folders, filename = self._segments(path)
        parent = self._ensure_folder(folders)
        self._client.upload(filename, parent, data)

    def write_cover(self, book_dir: str, data: bytes) -> None:
        self.write_book_file(f"{book_dir}/cover.jpg", data)

    def move(self, old_path: str, new_path: str) -> None:
        """Move a file, or a whole folder, to a new path."""
        old_segments = self._segments(old_path)
        new_segments = self._segments(new_path)
        *new_folders, new_name = new_segments
        new_parent = self._ensure_folder(new_folders)

        # A file move: re-parent/rename the single entry.
        resolved = self._resolve_file(old_path)
        if resolved is not None:
            self._client.move(resolved[1], new_parent, new_name)
            return

        # A folder move: re-parent/rename the folder itself.
        folder_id = self._resolve_folder(old_segments, create=False)
        if folder_id is None:
            raise FileNotFoundError(old_path)
        self._client.move(folder_id, new_parent, new_name)
        self._folder_cache.clear()  # ids stayed valid but cached paths shifted

    def delete(self, path: str) -> None:
        """Delete a file or a whole folder. A missing path is a no-op."""
        resolved = self._resolve_file(path)
        if resolved is not None:
            self._client.delete(resolved[1])
            return
        folder_id = self._resolve_folder(self._segments(path), create=False)
        if folder_id is not None:
            self._client.delete(folder_id)
            self._folder_cache.clear()

    # --- delivery -----------------------------------------------------------

    def download_link(self, path: str, *, expires_in: int) -> str:
        """Return a shareable Drive link for the file at *path*.

        Used to deliver an export: Drive serves the download itself. Raises
        ``FileNotFoundError`` if the file is absent.
        """
        resolved = self._resolve_file(path)
        if resolved is None:
            raise FileNotFoundError(path)
        return self._client.share_link(resolved[1], expires_in=expires_in)
