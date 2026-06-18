"""Tests for the system database (TDD).

The system database is Silverfish's own store, always separate from the book
library. In this phase it holds only persistent config (jobs stay in memory). It
is created and owned by our ORM, so it works on SQLite or Postgres. Two things
matter: config round-trips (set/get/overwrite/delete), and the schema is
isolated from both the Calibre schema and the native book schema — our system
tables must never be creatable into a book library.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.adapters import _calibre_schema as cs
from silverfish_core.adapters import _native_schema as ns
from silverfish_core.system import SystemBase, SystemDatabase


@pytest.fixture
def db(tmp_path: Path) -> Iterator[SystemDatabase]:
    database = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 'system.db'}")
    database.create_schema()
    yield database
    database.close()


class TestConfig:
    def test_get_missing_returns_none(self, db: SystemDatabase) -> None:
        assert db.get_config("smtp_host") is None

    def test_set_then_get(self, db: SystemDatabase) -> None:
        db.set_config("smtp_host", "smtp.example.com")
        assert db.get_config("smtp_host") == "smtp.example.com"

    def test_set_overwrites(self, db: SystemDatabase) -> None:
        db.set_config("k", "first")
        db.set_config("k", "second")
        assert db.get_config("k") == "second"

    def test_delete(self, db: SystemDatabase) -> None:
        db.set_config("k", "v")
        db.delete_config("k")
        assert db.get_config("k") is None

    def test_delete_missing_is_noop(self, db: SystemDatabase) -> None:
        db.delete_config("never-set")  # must not raise

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "system.db"
        first = SystemDatabase(conn_string=f"sqlite:///{path}")
        first.create_schema()
        first.set_config("machine_id", "7")
        first.close()

        second = SystemDatabase(conn_string=f"sqlite:///{path}")
        assert second.get_config("machine_id") == "7"
        second.close()


class TestIsolation:
    def test_system_metadata_is_distinct_from_book_schemas(self) -> None:
        # The system schema must be its own MetaData, never shared with a book
        # schema — that keeps system tables out of any book library.
        assert SystemBase.metadata is not cs.Base.metadata
        assert SystemBase.metadata is not ns.NativeBase.metadata

    def test_system_tables_are_not_book_tables(self) -> None:
        system_tables = set(SystemBase.metadata.tables)
        assert "books" not in system_tables
        assert "config" in system_tables
