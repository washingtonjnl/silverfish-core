"""Tests for the native (Silverfish-owned) book schema (TDD).

This is the schema the core CREATES and owns in standalone mode — distinct from
the Calibre schema, which we only ever read from an existing metadata.db. Two
invariants matter: (1) it must be isolated from the Calibre schema and the
system schema (no shared DeclarativeBase, no table-name collisions that could
let us write our tables into a Calibre library), and (2) create_all must
materialise the expected tables on a fresh database.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from silverfish_core.adapters import _calibre_schema as cs
from silverfish_core.adapters import _native_schema as ns


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite://")
    ns.NativeBase.metadata.create_all(eng)
    yield eng
    eng.dispose()


class TestIsolation:
    def test_native_metadata_is_not_calibre_metadata(self) -> None:
        # The sacred invariant: a different MetaData object than Calibre's, so
        # create_all on ours never touches (creates into) a Calibre library.
        assert ns.NativeBase.metadata is not cs.Base.metadata

    def test_native_metadata_owns_its_own_tables(self) -> None:
        # Our tables belong to our metadata, not Calibre's registry.
        assert "books" in ns.NativeBase.metadata.tables
        assert "books" not in cs.Base.metadata.tables or (
            cs.Base.metadata.tables["books"] is not ns.NativeBase.metadata.tables["books"]
        )


class TestCreateAll:
    def test_create_all_builds_book_tables(self, engine: Engine) -> None:
        tables = set(inspect(engine).get_table_names())
        assert "books" in tables
        assert "authors" in tables
        assert "data" in tables

    def test_book_id_is_a_big_integer(self, engine: Engine) -> None:
        # Snowflake ids need 64 bits; the PK must be BIGINT, not a 32-bit INTEGER.
        columns = {c["name"]: c for c in inspect(engine).get_columns("books")}
        assert "BIGINT" in str(columns["id"]["type"]).upper()
