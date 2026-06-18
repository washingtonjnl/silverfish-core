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


class TestMigrations:
    """Schema is managed by Alembic, so it can evolve without dropping data."""

    def _tables(self, db: SystemDatabase) -> set[str]:
        from sqlalchemy import inspect

        return set(inspect(db._engine).get_table_names())

    def test_migrate_creates_the_current_schema(self, tmp_path: Path) -> None:
        db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 's.db'}")
        db.migrate()
        tables = self._tables(db)
        # The current schema (incl. the evolved export_tokens), plus Alembic's
        # version table that records the applied revision.
        assert {"config", "jobs", "export_tokens", "alembic_version"} <= tables
        db.close()

    def test_export_tokens_has_the_current_columns(self, tmp_path: Path) -> None:
        from sqlalchemy import inspect

        db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 's.db'}")
        db.migrate()
        cols = {c["name"] for c in inspect(db._engine).get_columns("export_tokens")}
        # The columns the purge sweep relies on (the ones a stale create_all DB
        # was missing) are present.
        assert {"token", "location", "remote", "expires_at"} <= cols
        db.close()

    def test_migrate_is_idempotent(self, tmp_path: Path) -> None:
        db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 's.db'}")
        db.migrate()
        db.set_config("k", "v")
        db.migrate()  # running again must not error or wipe data
        assert db.get_config("k") == "v"
        db.close()

    def test_system_tables_are_not_book_tables(self) -> None:
        system_tables = set(SystemBase.metadata.tables)
        assert "books" not in system_tables
        assert "config" in system_tables


class TestMigrateAdoptsLegacyDatabase:
    """A pre-Alembic database (schema created by the old ``create_all``, with no
    Alembic stamp) must be adopted in place, not re-created. Migrating it must
    not fail with "table already exists" and must not drop its data.
    """

    def _make_legacy_db(self, path: Path) -> None:
        """Create a system DB the old way: tables exist, but no alembic stamp."""
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{path}")
        SystemBase.metadata.create_all(engine)
        # Put a row in so we can prove migration preserves it.
        db = SystemDatabase(conn_string=f"sqlite:///{path}")
        db.set_config("preexisting", "kept")
        db.close()
        engine.dispose()

    def test_migrate_adopts_legacy_db_without_error(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.db"
        self._make_legacy_db(path)

        db = SystemDatabase(conn_string=f"sqlite:///{path}")
        db.migrate()  # must not raise "table config already exists"
        # Data survives and the schema is now stamped at head.
        assert db.get_config("preexisting") == "kept"
        db.migrate()  # still idempotent afterwards
        db.close()

    def test_migrate_adopts_db_with_empty_alembic_version(self, tmp_path: Path) -> None:
        # The exact broken state seen in the field: alembic_version table exists
        # but holds no revision, so Alembic thinks nothing was applied.
        from sqlalchemy import create_engine, text

        path = tmp_path / "empty-stamp.db"
        self._make_legacy_db(path)
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        engine.dispose()

        db = SystemDatabase(conn_string=f"sqlite:///{path}")
        db.migrate()  # must not raise
        assert db.get_config("preexisting") == "kept"
        db.close()
