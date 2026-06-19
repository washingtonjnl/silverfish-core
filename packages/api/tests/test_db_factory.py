"""Tests for the database factories (TDD).

``build_library_repository`` maps settings to the right MetadataRepository:
the native repository in standalone mode (our schema, created on the spot) and
the Calibre repository in calibre mode (reading an existing metadata.db — which
must already exist, the core never creates it). ``build_system_db`` builds the
system store and creates its schema. Standalone mode supports both SQLite and
Postgres for the library (the native repo is portable SQLAlchemy).
"""

import os
import shutil
from pathlib import Path

import pytest

from silverfish_api.config import LibraryMode, Settings
from silverfish_api.db_factory import build_library_repository, build_system_db
from silverfish_core.adapters.repo_sql_native import SqlNativeRepository
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.ports.types import SortOrder

FIXTURE_DB = (
    Path(__file__).parents[2] / "core" / "tests" / "fixtures" / "calibre_library" / "metadata.db"
)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestStandalone:
    def test_builds_native_repository(self, tmp_path: Path) -> None:
        settings = _settings(library_mode=LibraryMode.STANDALONE, library_dir=tmp_path)
        repo = build_library_repository(settings)
        assert isinstance(repo, SqlNativeRepository)
        repo.close()

    def test_native_repository_is_usable(self, tmp_path: Path) -> None:
        settings = _settings(library_mode=LibraryMode.STANDALONE, library_dir=tmp_path)
        repo = build_library_repository(settings)
        # Schema is created on construction, so a listing works immediately.
        page = repo.list_books(page=1, page_size=10, sort=SortOrder())
        assert page.total == 0
        repo.close()

    def test_postgres_library_is_accepted(self, tmp_path: Path) -> None:
        # Standalone mode now supports Postgres for the library: the native repo
        # is portable SQLAlchemy and is validated against real Postgres in
        # test_repo_sql_native.py. The factory builds it against a real, ephemeral
        # Postgres (skipped where Docker is unavailable).
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:  # pragma: no cover - testcontainers is a dev dep
            pytest.skip("testcontainers not installed")
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
        try:
            container = PostgresContainer("postgres:16", driver="psycopg")
            container.start()
        except Exception as exc:  # pragma: no cover - environment without Docker
            pytest.skip(f"Postgres testcontainer unavailable: {exc}")
        try:
            settings = _settings(
                library_mode=LibraryMode.STANDALONE,
                library_dir=tmp_path,
                library_db=container.get_connection_url(),
            )
            repo = build_library_repository(settings)
            assert isinstance(repo, SqlNativeRepository)
            repo.close()
        finally:
            container.stop()


class TestCalibre:
    def test_reads_existing_metadata_db(self, tmp_path: Path) -> None:
        shutil.copy(FIXTURE_DB, tmp_path / "metadata.db")
        settings = _settings(library_mode=LibraryMode.CALIBRE, library_dir=tmp_path)
        repo = build_library_repository(settings)
        assert isinstance(repo, SqliteCalibreRepository)
        # The fixture has book id 1.
        assert repo.get_book(1) is not None
        repo.close()

    def test_missing_metadata_db_raises(self, tmp_path: Path) -> None:
        settings = _settings(library_mode=LibraryMode.CALIBRE, library_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match=r"metadata\.db|Calibre"):
            build_library_repository(settings)


class TestSystemDb:
    def test_builds_and_creates_schema(self, tmp_path: Path) -> None:
        settings = _settings(library_dir=tmp_path)
        system = build_system_db(settings)
        # Schema created => config round-trips immediately.
        system.set_config("k", "v")
        assert system.get_config("k") == "v"
        system.close()

    def test_missing_db_driver_gives_a_clear_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A Postgres (or other) URL whose driver isn't installed must fail with
        # an actionable message — name the extra — not a raw ModuleNotFoundError.
        monkeypatch.setenv("SILVERFISH_SYSTEM_DB", "postgresql+psycopg2://u:p@localhost/db")
        settings = _settings(library_dir=tmp_path)
        with pytest.raises(RuntimeError, match=r"driver|extra|install"):
            build_system_db(settings)
