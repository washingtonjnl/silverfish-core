"""Persistent store for finished export zips.

An export job zips a Calibre snapshot, registers the file here under an opaque
token, and emails the user a download link carrying that token. The token→file
mapping is persisted in the system database so an emitted link survives a
restart or deploy — an in-memory map would be lost, 404-ing every link emailed
before the restart.

Access is governed by a single, uniform rule: a time-to-live. Once the TTL
passes the token stops resolving and the file is deleted — the same behaviour
regardless of where the file lives (local now; the cloud equivalent later
revokes a presigned/share link after the same TTL). There is deliberately no
"expire after first download": that would need different logic for local vs.
cloud, where the download happens off-server and completion is unobservable.

The clock is injectable so expiry is deterministic in tests.
"""

import secrets
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select

from silverfish_core.system.db import SystemDatabase
from silverfish_core.system.models import ExportToken

# Number of random bytes in a token (URL-safe base64 makes it ~1.3x as long).
_TOKEN_BYTES = 24


class ExportStore:
    """Hold finished export files behind opaque, time-limited tokens.

    Backed by the system database, so tokens survive a restart.
    """

    def __init__(
        self,
        *,
        database: SystemDatabase,
        ttl_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._db = database
        self._ttl = ttl_seconds
        self._clock = clock

    @property
    def ttl_seconds(self) -> float:
        """How long a registered file stays downloadable."""
        return self._ttl

    def register(self, path: Path) -> str:
        """Register a finished file and return a fresh opaque token."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = self._clock() + self._ttl
        with self._db.session() as session:
            session.add(ExportToken(token=token, path=str(path), expires_at=expires_at))
            session.commit()
        return token

    def resolve(self, token: str) -> Path | None:
        """Return the file path for a valid token, or ``None``.

        If the token is unknown or expired, returns ``None``; an expired entry is
        removed and its file deleted on the way out.
        """
        with self._db.session() as session:
            row = session.get(ExportToken, token)
            if row is None:
                return None
            if self._clock() >= row.expires_at:
                path = Path(row.path)
                session.delete(row)
                session.commit()
                self._delete(path)
                return None
            return Path(row.path)

    def purge_expired(self) -> None:
        """Delete every expired entry and its file (periodic cleanup)."""
        now = self._clock()
        with self._db.session() as session:
            expired = session.scalars(
                select(ExportToken).where(ExportToken.expires_at <= now)
            ).all()
            paths = [Path(row.path) for row in expired]
            session.execute(delete(ExportToken).where(ExportToken.expires_at <= now))
            session.commit()
        for path in paths:
            self._delete(path)

    def _delete(self, path: Path) -> None:
        path.unlink(missing_ok=True)
