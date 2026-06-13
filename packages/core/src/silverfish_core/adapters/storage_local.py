"""Local-disk implementation of the ``FileStorage`` port.

All operations take library-relative paths and are confined to the configured
root directory. Any attempt to escape the root (``..`` segments, absolute paths,
symlink tricks) is rejected with ``ValueError`` before any I/O happens.
"""

import shutil
from pathlib import Path


class LocalFileStorage:
    """Store book files and covers under a single root directory on disk."""

    def __init__(self, root: Path) -> None:
        # Resolve once so traversal checks compare against the real root.
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, path: str) -> Path:
        """Resolve a library-relative *path* and ensure it stays under the root.

        Rejects empty paths, absolute paths and any ``..`` traversal. The result
        is the absolute, resolved path guaranteed to live inside the root.
        """
        if not path or not path.strip():
            msg = "Path must not be empty"
            raise ValueError(msg)

        candidate = Path(path)
        if candidate.is_absolute():
            msg = f"Absolute paths are invalid: {path!r}"
            raise ValueError(msg)

        # Resolve against the root, then confirm containment. ``resolve()``
        # collapses ``..`` and follows symlinks, so an escape becomes detectable.
        resolved = (self._root / candidate).resolve()
        if resolved != self._root and not resolved.is_relative_to(self._root):
            msg = f"Path escapes the library root (traversal): {path!r}"
            raise ValueError(msg)
        return resolved

    def read_book_file(self, path: str) -> bytes:
        return self._safe_path(path).read_bytes()

    def write_book_file(self, path: str, data: bytes) -> None:
        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def write_cover(self, book_dir: str, data: bytes) -> None:
        target = self._safe_path(book_dir) / "cover.jpg"
        # Re-check: book_dir was validated, and "cover.jpg" cannot escape it.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def move(self, old_path: str, new_path: str) -> None:
        source = self._safe_path(old_path)
        destination = self._safe_path(new_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

    def delete(self, path: str) -> None:
        target = self._safe_path(path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
