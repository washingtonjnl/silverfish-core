"""Tests for the storage factory and the storage selection setting.

Written before the implementation (TDD). The factory maps a storage *type* plus
config to a concrete ``FileStorage``. Today only ``local`` is implemented; the
factory is the single extension point where cloud backends (Drive, S3) plug in
later. The SaaS reuses this same factory per-request; the reference API builds
one global storage at boot.
"""

from pathlib import Path

import pytest

from silverfish_api.config import StorageType, load_settings
from silverfish_api.storage_factory import build_storage
from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.ports import FileStorage


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SILVERFISH_LIBRARY_DIR", "SILVERFISH_STORAGE"):
        monkeypatch.delenv(key, raising=False)


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

    def test_unimplemented_backend_raises_clear_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Selecting a backend that exists in the enum but is not wired yet must
        # fail loudly, not silently fall back.
        monkeypatch.setenv("SILVERFISH_STORAGE", "gdrive")
        settings = load_settings(env_dir=tmp_path)
        with pytest.raises(NotImplementedError, match="gdrive"):
            build_storage(settings)
