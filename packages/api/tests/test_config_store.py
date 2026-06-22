"""Tests for the runtime config store and the generic /config routes.

The config store is a key/value layer over the system DB with an allowlist and
write-only secrets; SMTP resolves as DB-overrides-env. The routes expose generic
read (by key) and write (by map) so a UI can edit, say, just kindle_email.
"""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_api.config import Settings, load_settings
from silverfish_api.config_store import (
    read_config,
    resolve_smtp_settings,
    write_config,
)
from silverfish_core.system import SystemDatabase

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"


@pytest.fixture
def system_db(tmp_path: Path) -> Iterator[SystemDatabase]:
    db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 'system.db'}")
    db.migrate()
    yield db
    db.close()


@pytest.fixture
def empty_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # No SMTP env set, so reads reflect only the store.
    for key in list(os.environ):
        if key.startswith("SILVERFISH_SMTP"):
            monkeypatch.delenv(key, raising=False)
    return load_settings(env_dir=tmp_path)


class TestConfigStore:
    def test_unknown_keys_are_ignored_on_read(
        self, system_db: SystemDatabase, empty_settings: Settings
    ) -> None:
        assert read_config(system_db, ["not_a_key"], empty_settings) == {}

    def test_unset_known_key_reads_none(
        self, system_db: SystemDatabase, empty_settings: Settings
    ) -> None:
        assert read_config(system_db, ["kindle_email"], empty_settings) == {"kindle_email": None}

    def test_write_then_read_roundtrip(
        self, system_db: SystemDatabase, empty_settings: Settings
    ) -> None:
        write_config(system_db, {"kindle_email": "me@kindle.com"})
        assert read_config(system_db, ["kindle_email"], empty_settings) == {
            "kindle_email": "me@kindle.com"
        }

    def test_unknown_key_on_write_raises(self, system_db: SystemDatabase) -> None:
        with pytest.raises(ValueError, match="Unknown config keys"):
            write_config(system_db, {"evil": "x"})

    def test_secret_is_write_only(
        self, system_db: SystemDatabase, empty_settings: Settings
    ) -> None:
        write_config(system_db, {"smtp_password": "hunter2"})
        # Read never returns the secret value; just a "set" placeholder.
        out = read_config(system_db, ["smtp_password"], empty_settings)
        assert out["smtp_password"] == "********"
        assert system_db.get_config("smtp_password") == "hunter2"

    def test_blank_secret_clears_it(
        self, system_db: SystemDatabase, empty_settings: Settings
    ) -> None:
        write_config(system_db, {"smtp_password": "hunter2"})
        write_config(system_db, {"smtp_password": ""})
        assert read_config(system_db, ["smtp_password"], empty_settings) == {"smtp_password": None}

    def test_env_value_shows_when_no_override(
        self, system_db: SystemDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # SMTP host comes from env and there's no stored override → effective is env.
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "env.example.com")
        settings = load_settings(env_dir=tmp_path)
        assert read_config(system_db, ["smtp_host"], settings) == {"smtp_host": "env.example.com"}

    def test_store_overrides_env_on_read(
        self, system_db: SystemDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "env.example.com")
        settings = load_settings(env_dir=tmp_path)
        write_config(system_db, {"smtp_host": "db.example.com"})
        assert read_config(system_db, ["smtp_host"], settings) == {"smtp_host": "db.example.com"}

    def test_env_password_reads_as_masked(
        self, system_db: SystemDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A password from env (no override) still reads back masked, never plain.
        monkeypatch.setenv("SILVERFISH_SMTP_PASSWORD", "fromenv")
        settings = load_settings(env_dir=tmp_path)
        assert read_config(system_db, ["smtp_password"], settings) == {"smtp_password": "********"}

    def test_partial_write_leaves_others_untouched(self, system_db: SystemDatabase) -> None:
        write_config(system_db, {"smtp_host": "smtp.example.com"})
        write_config(system_db, {"kindle_email": "me@kindle.com"})
        assert system_db.get_config("smtp_host") == "smtp.example.com"

    def test_resolve_overrides_env(self, system_db: SystemDatabase, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        base = settings.model_copy(update={"smtp_host": "env-host", "smtp_port": 25})
        write_config(system_db, {"smtp_host": "db-host", "smtp_port": "2525"})
        resolved = resolve_smtp_settings(base, system_db)
        assert resolved.smtp_host == "db-host"
        assert resolved.smtp_port == 2525

    def test_resolve_falls_back_to_env(self, system_db: SystemDatabase, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        base = settings.model_copy(update={"smtp_host": "env-host"})
        resolved = resolve_smtp_settings(base, system_db)
        assert resolved.smtp_host == "env-host"


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    with TestClient(create_app()) as test_client:
        yield test_client


class TestConfigRoutes:
    def test_get_returns_requested_keys(self, client: TestClient) -> None:
        client.post("/config", json={"values": {"kindle_email": "me@kindle.com"}})
        res = client.get("/config", params={"keys": ["kindle_email"]})
        assert res.status_code == 200
        assert res.json() == {"kindle_email": "me@kindle.com"}

    def test_get_masks_the_password(self, client: TestClient) -> None:
        client.post("/config", json={"values": {"smtp_password": "hunter2"}})
        res = client.get("/config", params={"keys": ["smtp_password"]})
        assert res.json() == {"smtp_password": "********"}

    def test_post_unknown_key_is_422(self, client: TestClient) -> None:
        res = client.post("/config", json={"values": {"nope": "x"}})
        assert res.status_code == 422

    def test_post_returns_masked_readback(self, client: TestClient) -> None:
        res = client.post(
            "/config",
            json={"values": {"kindle_email": "a@b.com", "smtp_password": "p"}},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["kindle_email"] == "a@b.com"
        assert body["smtp_password"] == "********"
