"""Tests for the export service (TDD).

The service ties the pieces together: it runs the CalibreExporter into a
temporary directory, zips the result, and produces a download URL plus the
"export ready" email. Delivery depends on the storage backend:

* local (no presigned capability) — the zip is registered in the ExportStore
  under a token, removed from the temp tree, and the URL points at the API's
  download route.
* S3 / presigned-capable — the zip is uploaded to storage and the URL is a
  direct, time-limited link to it (the download bypasses the API server).

The exporter and storage are faked so these tests need no Calibre or AWS.
"""

import zipfile
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest

from silverfish_api.export_service import ExportService
from silverfish_api.export_store import ExportStore
from silverfish_core.system.db import SystemDatabase

_TTL = 3600


class _FakeExporter:
    def __init__(self) -> None:
        self.book_ids: object = "unset"

    def export(self, destination: Path, book_ids: object = None) -> object:
        self.book_ids = book_ids
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "metadata.db").write_bytes(b"calibre db")
        book_dir = destination / "Stephen King" / "It (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "It - Stephen King.epub").write_bytes(b"EPUBDATA")

        class _Result:
            book_count = 1

        return _Result()


class _LocalStorage:
    """A FileStorage with no presigned capability (forces the token route)."""

    def read_book_file(self, path: str) -> bytes:
        raise NotImplementedError

    def write_book_file(self, path: str, data: bytes) -> None: ...
    def write_cover(self, book_dir: str, data: bytes) -> None: ...
    def move(self, old_path: str, new_path: str) -> None: ...
    def delete(self, path: str) -> None: ...


class _PresignedStorage(_LocalStorage):
    """A FileStorage that also offers presigned URLs (the S3 case)."""

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def write_book_file(self, path: str, data: bytes) -> None:
        self.uploaded[path] = data

    def download_link(self, path: str, *, expires_in: int) -> str:
        return f"https://s3.example.com/{path}?expires={expires_in}&sig=abc"


def _clock() -> float:
    return 1000.0


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ExportStore]:
    db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 'system.db'}")
    db.create_schema()
    yield ExportStore(database=db, ttl_seconds=_TTL, clock=_clock)
    db.close()


def _service(tmp_path: Path, store: ExportStore, storage: object) -> ExportService:
    return ExportService(
        exporter=_FakeExporter(),  # type: ignore[arg-type]
        store=store,
        storage=storage,  # type: ignore[arg-type]
        work_dir=tmp_path / "work",
        public_base_url="http://localhost:8000",
    )


class TestLocalDelivery:
    def test_url_points_at_download_route(self, tmp_path: Path, store: ExportStore) -> None:
        service = _service(tmp_path, store, _LocalStorage())
        result = service.run_export()
        assert result.download_url.startswith("http://localhost:8000/export/download/")

    def test_zip_is_registered_and_resolvable(self, tmp_path: Path, store: ExportStore) -> None:
        service = _service(tmp_path, store, _LocalStorage())
        result = service.run_export()
        token = result.download_url.rsplit("/", 1)[1]
        path = store.resolve(token)
        assert path is not None and zipfile.is_zipfile(path)

    def test_intermediate_directory_is_removed(self, tmp_path: Path, store: ExportStore) -> None:
        service = _service(tmp_path, store, _LocalStorage())
        service.run_export()
        work = tmp_path / "work"
        assert [p for p in work.rglob("*") if p.is_dir()] == []


class TestPresignedDelivery:
    def test_url_is_the_presigned_link(self, tmp_path: Path, store: ExportStore) -> None:
        storage = _PresignedStorage()
        service = _service(tmp_path, store, storage)
        result = service.run_export()
        assert result.download_url.startswith("https://s3.example.com/")
        assert "expires=3600" in result.download_url

    def test_zip_is_uploaded_to_storage(self, tmp_path: Path, store: ExportStore) -> None:
        storage = _PresignedStorage()
        service = _service(tmp_path, store, storage)
        service.run_export()
        assert len(storage.uploaded) == 1
        key, data = next(iter(storage.uploaded.items()))
        assert key.startswith("exports/")
        assert data[:2] == b"PK"  # a real zip

    def test_no_local_zip_left_behind(self, tmp_path: Path, store: ExportStore) -> None:
        storage = _PresignedStorage()
        service = _service(tmp_path, store, storage)
        service.run_export()
        work = tmp_path / "work"
        assert [p for p in work.rglob("*") if p.is_file()] == []


class TestEmail:
    def test_builds_ready_email_with_url(self, tmp_path: Path, store: ExportStore) -> None:
        service = _service(tmp_path, store, _LocalStorage())
        result = service.run_export()
        message = service.build_ready_email(
            to_email="me@example.com", download_url=result.download_url
        )
        assert isinstance(message, EmailMessage)
        assert message["To"] == "me@example.com"
        body = message.get_content()
        assert result.download_url in body

    def test_email_window_follows_ttl_as_hh_mm(self, tmp_path: Path, store: ExportStore) -> None:
        # The stated expiry window derives from the store's TTL, not a hardcode.
        # _TTL = 3600s = 60 minutes = 1h00.
        service = _service(tmp_path, store, _LocalStorage())
        message = service.build_ready_email(to_email="me@x.com", download_url="http://x/y")
        assert "1h00" in message.get_content()

    def test_email_window_for_24h_ttl(self, tmp_path: Path) -> None:
        # The default TTL is 24h -> 24h00.
        db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 's.db'}")
        db.create_schema()
        store = ExportStore(database=db, ttl_seconds=1440 * 60, clock=_clock)
        service = _service(tmp_path, store, _LocalStorage())
        message = service.build_ready_email(to_email="me@x.com", download_url="http://x/y")
        assert "24h00" in message.get_content()
        db.close()
