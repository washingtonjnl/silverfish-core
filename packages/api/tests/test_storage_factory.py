"""Tests for the storage factory and the storage selection setting.

Written before the implementation (TDD). The factory maps a storage *type* plus
config to a concrete ``FileStorage``. Today only ``local`` is implemented; the
factory is the single extension point where cloud backends (Drive, S3) plug in
later. The SaaS reuses this same factory per-request; the reference API builds
one global storage at boot.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from moto import mock_aws

from silverfish_api.config import StorageType, load_settings
from silverfish_api.storage_factory import build_storage
from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.adapters.storage_s3 import S3Storage
from silverfish_core.ports import FileStorage

_STORAGE_ENV = (
    "SILVERFISH_LIBRARY_DIR",
    "SILVERFISH_STORAGE",
    "SILVERFISH_S3_BUCKET",
    "SILVERFISH_S3_REGION",
    "SILVERFISH_S3_PREFIX",
    "SILVERFISH_S3_ACCESS_KEY_ID",
    "SILVERFISH_S3_SECRET_ACCESS_KEY",
    "SILVERFISH_GDRIVE_FOLDER_ID",
    "SILVERFISH_GDRIVE_FOLDER_NAME",
    "SILVERFISH_GDRIVE_CLIENT_ID",
    "SILVERFISH_GDRIVE_CLIENT_SECRET",
    "SILVERFISH_GDRIVE_REFRESH_TOKEN",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _STORAGE_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def _mock_s3() -> Iterator[None]:
    with mock_aws():
        yield


class TestStorageSetting:
    def test_defaults_to_local(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.storage == StorageType.LOCAL

    def test_reads_storage_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_STORAGE", "local")
        settings = load_settings(env_dir=tmp_path)
        assert settings.storage == StorageType.LOCAL


class TestFactory:
    def test_builds_local_storage(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        object.__setattr__(settings, "library_dir", tmp_path)
        storage = build_storage(settings)
        assert isinstance(storage, LocalFileStorage)
        assert isinstance(storage, FileStorage)

    def test_local_storage_rooted_at_library_dir(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        object.__setattr__(settings, "library_dir", tmp_path)
        storage = build_storage(settings)
        storage.write_book_file("Author/Book (1)/book.epub", b"data")
        assert (tmp_path / "Author" / "Book (1)" / "book.epub").read_bytes() == b"data"


class TestGDrive:
    def test_gdrive_without_credentials_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_STORAGE", "gdrive")  # no client id/secret
        settings = load_settings(env_dir=tmp_path)
        with pytest.raises(ValueError, match=r"CLIENT_ID|CLIENT_SECRET"):
            build_storage(settings)

    def test_gdrive_without_refresh_token_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # folder_id is now optional (the app creates the root folder), but the
        # OAuth credentials are still required.
        monkeypatch.setenv("SILVERFISH_STORAGE", "gdrive")
        monkeypatch.setenv("SILVERFISH_GDRIVE_CLIENT_ID", "cid")
        monkeypatch.setenv("SILVERFISH_GDRIVE_CLIENT_SECRET", "csecret")
        settings = load_settings(env_dir=tmp_path)
        with pytest.raises(ValueError, match=r"REFRESH_TOKEN|refresh"):
            build_storage(settings)


class TestS3:
    def test_builds_s3_storage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _mock_s3: None
    ) -> None:
        monkeypatch.setenv("SILVERFISH_STORAGE", "s3")
        monkeypatch.setenv("SILVERFISH_S3_BUCKET", "my-bucket")
        monkeypatch.setenv("SILVERFISH_S3_REGION", "us-east-1")
        monkeypatch.setenv("SILVERFISH_S3_ACCESS_KEY_ID", "test")
        monkeypatch.setenv("SILVERFISH_S3_SECRET_ACCESS_KEY", "test")
        settings = load_settings(env_dir=tmp_path)
        storage = build_storage(settings)
        assert isinstance(storage, S3Storage)
        assert isinstance(storage, FileStorage)

    def test_s3_without_bucket_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_STORAGE", "s3")  # no bucket set
        settings = load_settings(env_dir=tmp_path)
        with pytest.raises(ValueError, match=r"S3_BUCKET|bucket"):
            build_storage(settings)
