"""Persistent store for finished export zips and their cleanup.

An export job zips a Calibre snapshot and registers it here under an opaque token
with a time-to-live. The token→location map is persisted in the system database
so an emitted link survives a restart or deploy (an in-memory map would be lost,
404-ing every link emailed before the restart).

A zip lives in one of two places, both tracked here so expiry deletes the file —
not just the link:

* local — a disk path, served by the API's download route; ``resolve`` returns
  it and an expired entry is ``unlink``-ed.
* remote — a storage key (S3/Drive), downloaded directly via a link the backend
  serves; on expiry the object is deleted through the storage adapter.

Expiry is uniform: a single TTL. Once it passes the token stops resolving and
the file is deleted wherever it lives. The clock is injectable for tests.
"""

import secrets
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select

from silverfish_core.ports import FileStorage
from silverfish_core.system.db import SystemDatabase
from silverfish_core.system.models import ExportToken

# Number of random bytes in a token (URL-safe base64 makes it ~1.3x as long).
_TOKEN_BYTES = 24


class ExportStore:
    """Track finished export files behind opaque, time-limited tokens.

    Backed by the system database (tokens survive a restart). *storage* is used
    to delete remote (S3/Drive) export objects on expiry; pass it whenever remote
    exports are possible.
    """

    def __init__(
        self,
        *,
        database: SystemDatabase,
        ttl_seconds: float,
        clock: Callable[[], float],
        storage: FileStorage | None = None,
    ) -> None:
        self._db = database
        self._ttl = ttl_seconds
        self._clock = clock
        self._storage = storage

    @property
    def ttl_seconds(self) -> float:
        """How long a registered file stays downloadable."""
        return self._ttl

    def register(self, path: Path) -> str:
        """Register a local file and return a fresh opaque token.

        The token is used by the API download route to serve the file.
        """
        return self._add(str(path), remote=False)

    def register_remote(self, key: str) -> str:
        """Register a remote storage object (downloaded via a backend link).

        Tracked only so expiry can delete the object; the token is not served by
        the API (the emailed link points straight at the backend).
        """
        return self._add(key, remote=True)

    def resolve(self, token: str) -> Path | None:
        """Return the local file path for a valid local token, or ``None``.

        Unknown, expired or remote tokens return ``None``; an expired entry is
        removed and its file deleted on the way out.
        """
        with self._db.session() as session:
            row = session.get(ExportToken, token)
            if row is None:
                return None
            if self._clock() >= row.expires_at:
                location, remote = row.location, row.remote
                session.delete(row)
                session.commit()
                self._delete(location, remote=remote)
                return None
            if row.remote:
                return None
            return Path(row.location)

    def purge_expired(self) -> None:
        """Delete every expired entry and its file (local or remote)."""
        now = self._clock()
        with self._db.session() as session:
            expired = session.scalars(
                select(ExportToken).where(ExportToken.expires_at <= now)
            ).all()
            targets = [(row.location, row.remote) for row in expired]
            session.execute(delete(ExportToken).where(ExportToken.expires_at <= now))
            session.commit()
        for location, remote in targets:
            self._delete(location, remote=remote)

    # --- internals ----------------------------------------------------------

    def _add(self, location: str, *, remote: bool) -> str:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = self._clock() + self._ttl
        with self._db.session() as session:
            session.add(
                ExportToken(token=token, location=location, remote=remote, expires_at=expires_at)
            )
            session.commit()
        return token

    def _delete(self, location: str, *, remote: bool) -> None:
        """Delete the export file: a storage object if remote, else a disk file."""
        if remote:
            if self._storage is not None:
                self._storage.delete(location)
            return
        Path(location).unlink(missing_ok=True)
