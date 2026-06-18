"""Tests for the persistent export store (TDD).

A finished export zip is registered under an opaque token with a time-to-live.
The store hands back the file path for a valid token and, once the TTL passes,
treats the token as gone and deletes the file — a single, uniform expiry rule
(by time). The token→file map is persisted in the system database, so a link
survives a restart. The clock is injected so expiry is deterministic in tests.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_api.export_store import ExportStore
from silverfish_core.system.db import SystemDatabase


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def database(tmp_path: Path) -> Iterator[SystemDatabase]:
    db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 'system.db'}")
    db.create_schema()
    yield db
    db.close()


@pytest.fixture
def store(database: SystemDatabase, clock: _Clock) -> Iterator[ExportStore]:
    yield ExportStore(database=database, ttl_seconds=3600, clock=clock)


def _make_zip(tmp_path: Path, name: str = "export.zip") -> Path:
    path = tmp_path / name
    path.write_bytes(b"PK\x03\x04 fake zip")
    return path


class TestRegisterAndResolve:
    def test_register_returns_opaque_token(self, store: ExportStore, tmp_path: Path) -> None:
        token = store.register(_make_zip(tmp_path))
        assert isinstance(token, str)
        assert len(token) >= 16  # not guessable

    def test_resolve_returns_path_for_valid_token(self, store: ExportStore, tmp_path: Path) -> None:
        zip_path = _make_zip(tmp_path)
        token = store.register(zip_path)
        assert store.resolve(token) == zip_path

    def test_unknown_token_resolves_to_none(self, store: ExportStore) -> None:
        assert store.resolve("nope") is None

    def test_token_survives_a_restart(
        self, database: SystemDatabase, clock: _Clock, tmp_path: Path
    ) -> None:
        # Register with one store instance, resolve with a fresh one over the
        # same database — as if the process had restarted. This is the bug fix:
        # an in-memory map would have lost the token here.
        zip_path = _make_zip(tmp_path)
        token = ExportStore(database=database, ttl_seconds=3600, clock=clock).register(zip_path)
        fresh = ExportStore(database=database, ttl_seconds=3600, clock=clock)
        assert fresh.resolve(token) == zip_path


class TestExpiry:
    def test_expired_token_resolves_to_none(
        self, store: ExportStore, clock: _Clock, tmp_path: Path
    ) -> None:
        token = store.register(_make_zip(tmp_path))
        clock.now += 3601  # past the TTL
        assert store.resolve(token) is None

    def test_expired_file_is_deleted_on_access(
        self, store: ExportStore, clock: _Clock, tmp_path: Path
    ) -> None:
        zip_path = _make_zip(tmp_path)
        token = store.register(zip_path)
        clock.now += 3601
        store.resolve(token)
        assert not zip_path.exists()

    def test_valid_token_keeps_file(
        self, store: ExportStore, clock: _Clock, tmp_path: Path
    ) -> None:
        zip_path = _make_zip(tmp_path)
        token = store.register(zip_path)
        clock.now += 1800  # within TTL
        store.resolve(token)
        assert zip_path.exists()


class TestCleanup:
    def test_purge_expired_removes_files_and_entries(
        self, store: ExportStore, clock: _Clock, tmp_path: Path
    ) -> None:
        fresh = _make_zip(tmp_path, "fresh.zip")
        stale = _make_zip(tmp_path, "stale.zip")
        store.register(fresh)
        stale_token = store.register(stale)
        clock.now += 3601
        # Re-register a fresh one after advancing so it is within TTL.
        fresh2 = _make_zip(tmp_path, "fresh2.zip")
        fresh2_token = store.register(fresh2)

        store.purge_expired()

        assert not stale.exists()
        assert store.resolve(stale_token) is None
        assert fresh2.exists()
        assert store.resolve(fresh2_token) == fresh2
