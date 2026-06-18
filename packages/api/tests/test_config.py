"""Tests for API settings loading.

Written before the implementation (TDD). Precedence (highest first):

    real environment variable  >  .env.local  >  .env  >  built-in default

The library layer now has two independent databases (book library + system
store), each a SQLite path or a Postgres URL, plus a library mode that selects
whether the core owns the database (standalone) or reads an existing Calibre one
(calibre). ``SILVERFISH_LIBRARY_DIR`` is kept as a convenience that derives all
three local defaults when the explicit knobs are unset.
"""

from pathlib import Path

import pytest

from silverfish_api.config import LibraryMode, Settings, load_settings

_ENV_KEYS = (
    "SILVERFISH_LIBRARY_DIR",
    "SILVERFISH_LIBRARY_MODE",
    "SILVERFISH_LIBRARY_DB",
    "SILVERFISH_SYSTEM_DB",
    "SILVERFISH_STORAGE_DIR",
    "SILVERFISH_STORAGE",
    "SILVERFISH_CALIBRE_BIN_DIR",
    "SILVERFISH_MACHINE_ID",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class TestMode:
    def test_defaults_to_standalone(self, tmp_path: Path) -> None:
        assert load_settings(env_dir=tmp_path).library_mode is LibraryMode.STANDALONE

    def test_reads_calibre_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
        assert load_settings(env_dir=tmp_path).library_mode is LibraryMode.CALIBRE


class TestLibraryDbResolution:
    def test_standalone_default_derives_native_db_from_dir(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        # Standalone owns the DB; the local default is our own file, not metadata.db.
        assert settings.resolved_library_db == f"sqlite:///{settings.library_dir / 'library.db'}"

    def test_calibre_default_derives_metadata_db_from_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
        settings = load_settings(env_dir=tmp_path)
        # Calibre mode reads an existing metadata.db in the library dir.
        assert settings.resolved_library_db == f"sqlite:///{settings.library_dir / 'metadata.db'}"

    def test_explicit_library_db_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_LIBRARY_DB", "postgresql+psycopg://u:p@host/lib")
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_library_db == "postgresql+psycopg://u:p@host/lib"

    def test_bare_sqlite_path_is_normalised_to_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_LIBRARY_DB", "/data/books.db")
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_library_db == "sqlite:////data/books.db"


class TestSystemDbResolution:
    def test_default_derives_separate_system_db(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        # System store is always a separate file from the library.
        assert settings.resolved_system_db == f"sqlite:///{settings.library_dir / 'system.db'}"
        assert settings.resolved_system_db != settings.resolved_library_db

    def test_explicit_system_db_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_SYSTEM_DB", "postgresql+psycopg://u:p@host/sys")
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_system_db == "postgresql+psycopg://u:p@host/sys"

    def test_library_and_system_can_target_different_backends(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Calibre SQLite for books, Postgres for the system store — a valid combo.
        monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
        monkeypatch.setenv("SILVERFISH_LIBRARY_DB", "/calibre/metadata.db")
        monkeypatch.setenv("SILVERFISH_SYSTEM_DB", "postgresql+psycopg://u:p@host/sys")
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_library_db == "sqlite:////calibre/metadata.db"
        assert settings.resolved_system_db == "postgresql+psycopg://u:p@host/sys"


class TestStorageDir:
    def test_defaults_to_library_dir(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_storage_dir == settings.library_dir

    def test_explicit_storage_dir_is_independent_of_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Storage is decoupled from the DB: files can live apart from metadata.
        monkeypatch.setenv("SILVERFISH_STORAGE_DIR", "/mnt/books")
        monkeypatch.setenv("SILVERFISH_LIBRARY_DB", "postgresql+psycopg://u:p@host/lib")
        settings = load_settings(env_dir=tmp_path)
        assert settings.resolved_storage_dir == Path("/mnt/books")


class TestLibraryDirShortcut:
    def test_default_library_dir(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir.name == "silverfish-library"

    def test_library_dir_from_dotenv(self, tmp_path: Path) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/lib\n")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/lib")

    def test_dotenv_local_overrides_dotenv(self, tmp_path: Path) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/from-env\n")
        _write(tmp_path / ".env.local", "SILVERFISH_LIBRARY_DIR=/data/from-local\n")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/from-local")

    def test_real_env_var_wins_over_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/from-env\n")
        monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", "/data/from-real-env")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/from-real-env")


class TestMachineId:
    def test_defaults_to_zero(self, tmp_path: Path) -> None:
        assert load_settings(env_dir=tmp_path).machine_id == 0

    def test_reads_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_MACHINE_ID", "5")
        assert load_settings(env_dir=tmp_path).machine_id == 5


class TestCalibreBinDir:
    def test_defaults_to_none(self, tmp_path: Path) -> None:
        assert load_settings(env_dir=tmp_path).calibre_bin_dir is None

    def test_reads_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_CALIBRE_BIN_DIR", "/opt/calibre")
        assert load_settings(env_dir=tmp_path).calibre_bin_dir == Path("/opt/calibre")


class TestType:
    def test_returns_settings_instance(self, tmp_path: Path) -> None:
        assert isinstance(load_settings(env_dir=tmp_path), Settings)
