"""Ephemeral store for finished export zips.

An export job zips a Calibre snapshot, registers the file here under an opaque
token, and emails the user a download link carrying that token. Access is
governed by a single, uniform rule: a time-to-live. Once the TTL passes the
token stops resolving and the file is deleted — the same behaviour regardless of
where the file lives (local now; the cloud equivalent later revokes a
presigned/share link after the same TTL). There is deliberately no
"expire after first download": that would need different logic for local vs.
cloud, where the download happens off-server and completion is unobservable.

The clock is injectable so expiry is deterministic in tests.
"""

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Number of random bytes in a token (URL-safe base64 makes it ~1.3x as long).
_TOKEN_BYTES = 24


@dataclass(frozen=True, slots=True)
class _Entry:
    path: Path
    expires_at: float


class ExportStore:
    """Hold finished export files behind opaque, time-limited tokens."""

    def __init__(self, *, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def register(self, path: Path) -> str:
        """Register a finished file and return a fresh opaque token."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = self._clock() + self._ttl
        with self._lock:
            self._entries[token] = _Entry(path=path, expires_at=expires_at)
        return token

    def resolve(self, token: str) -> Path | None:
        """Return the file path for a valid token, or ``None``.

        If the token is unknown or expired, returns ``None``; an expired entry is
        removed and its file deleted on the way out.
        """
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if self._clock() >= entry.expires_at:
                del self._entries[token]
                self._delete(entry.path)
                return None
            return entry.path

    def purge_expired(self) -> None:
        """Delete every expired entry and its file (periodic cleanup)."""
        now = self._clock()
        with self._lock:
            expired = [t for t, e in self._entries.items() if now >= e.expires_at]
            for token in expired:
                entry = self._entries.pop(token)
                self._delete(entry.path)

    def _delete(self, path: Path) -> None:
        path.unlink(missing_ok=True)
