"""Tests for API settings loading.

Written before the implementation (TDD). Precedence (highest first):

    real environment variable  >  .env.local  >  .env  >  built-in default

Secrets live in .env.local (gitignored); .env holds non-secret defaults.
"""

from pathlib import Path

import pytest

from silverfish_api.config import Settings, load_settings


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SILVERFISH_LIBRARY_DIR", "SILVERFISH_STORAGE", "SILVERFISH_CALIBRE_BIN_DIR"):
        monkeypatch.delenv(key, raising=False)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class TestDefaults:
    def test_default_library_dir_when_nothing_set(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir.name == "silverfish-library"

    def test_metadata_db_path_derives_from_library_dir(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.metadata_db == settings.library_dir / "metadata.db"


class TestEnvFile:
    def test_reads_library_dir_from_dotenv(self, tmp_path: Path) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/lib\n")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/lib")

    def test_dotenv_local_overrides_dotenv(self, tmp_path: Path) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/from-env\n")
        _write(tmp_path / ".env.local", "SILVERFISH_LIBRARY_DIR=/data/from-local\n")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/from-local")


class TestEnvVarPrecedence:
    def test_real_env_var_wins_over_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path / ".env", "SILVERFISH_LIBRARY_DIR=/data/from-env\n")
        _write(tmp_path / ".env.local", "SILVERFISH_LIBRARY_DIR=/data/from-local\n")
        monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", "/data/from-real-env")
        settings = load_settings(env_dir=tmp_path)
        assert settings.library_dir == Path("/data/from-real-env")


class TestCalibreBinDir:
    def test_defaults_to_none(self, tmp_path: Path) -> None:
        assert load_settings(env_dir=tmp_path).calibre_bin_dir is None

    def test_reads_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_CALIBRE_BIN_DIR", "/opt/calibre")
        assert load_settings(env_dir=tmp_path).calibre_bin_dir == Path("/opt/calibre")


class TestType:
    def test_returns_settings_instance(self, tmp_path: Path) -> None:
        assert isinstance(load_settings(env_dir=tmp_path), Settings)
