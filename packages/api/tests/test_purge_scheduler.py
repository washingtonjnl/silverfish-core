"""Tests for the periodic export-purge scheduler (TDD).

Expired exports — especially remote ones, whose links are served by the storage
backend and never re-resolved through the API — need an active sweep to delete
the files. The scheduler runs ``purge_expired`` once on start (clearing anything
that lapsed while the server was down) and then on an interval, on a daemon
thread. The interval wait is event-based, so ``stop`` returns immediately.
"""

import threading
import time
from collections.abc import Callable

from silverfish_api.purge_scheduler import PurgeScheduler


class _CountingStore:
    def __init__(self) -> None:
        self.purges = 0
        self._lock = threading.Lock()

    def purge_expired(self) -> None:
        with self._lock:
            self.purges += 1


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


class TestPurgeScheduler:
    def test_purges_once_on_start(self) -> None:
        store = _CountingStore()
        scheduler = PurgeScheduler(store=store, interval_seconds=999)
        scheduler.start()
        try:
            _wait_until(lambda: store.purges >= 1)
        finally:
            scheduler.stop()
        assert store.purges >= 1

    def test_purges_again_on_interval(self) -> None:
        store = _CountingStore()
        scheduler = PurgeScheduler(store=store, interval_seconds=0.05)
        scheduler.start()
        try:
            _wait_until(lambda: store.purges >= 3)
        finally:
            scheduler.stop()
        assert store.purges >= 3

    def test_stop_is_prompt_and_idempotent(self) -> None:
        # A long interval must not delay stop (event-based wait), and a second
        # stop must not raise.
        store = _CountingStore()
        scheduler = PurgeScheduler(store=store, interval_seconds=999)
        scheduler.start()
        started = time.monotonic()
        scheduler.stop()
        scheduler.stop()
        assert time.monotonic() - started < 1.0

    def test_purge_error_does_not_kill_the_thread(self) -> None:
        class _Boom:
            def __init__(self) -> None:
                self.calls = 0

            def purge_expired(self) -> None:
                self.calls += 1
                raise RuntimeError("boom")

        store = _Boom()
        scheduler = PurgeScheduler(store=store, interval_seconds=0.05)
        scheduler.start()
        try:
            # Keeps sweeping despite each purge raising.
            _wait_until(lambda: store.calls >= 2)
        finally:
            scheduler.stop()
        assert store.calls >= 2
