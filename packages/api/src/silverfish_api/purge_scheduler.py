"""Periodic sweep that deletes expired export files.

Local exports are cleaned lazily when an expired token is resolved, but a remote
export's link is served by the storage backend and never re-resolved through the
API — so without an active sweep its object would linger forever. This scheduler
runs ``purge_expired`` once on start (clearing anything that lapsed while the
server was down) and then every ``interval_seconds``, on a daemon thread. The
interval wait is event-based, so ``stop`` returns promptly even with a long
interval. The sweep itself is a ``DELETE WHERE expires_at <= now`` over the
export tokens plus the file deletes — never a scan of any job list.
"""

import logging
import threading
from typing import Protocol

logger = logging.getLogger("silverfish")


class _Purgeable(Protocol):
    def purge_expired(self) -> None: ...


class PurgeScheduler:
    """Run ``store.purge_expired`` on start and every *interval_seconds*."""

    def __init__(self, *, store: _Purgeable, interval_seconds: float) -> None:
        self._store = store
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="export-purge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._purge_once()
            # Event-based wait: returns immediately on stop, else after interval.
            self._stop.wait(self._interval)

    def _purge_once(self) -> None:
        try:
            self._store.purge_expired()
        except Exception:
            # A purge failure must never kill the sweep thread; log and retry
            # next interval.
            logger.exception("Export purge failed")
