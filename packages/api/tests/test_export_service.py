"""Tests for the export service (TDD).

The service ties the pieces together: it runs the CalibreExporter into a
temporary directory, zips the result, registers the zip in the ExportStore under
a token, removes the intermediate directory (only the zip survives), and builds
the "your export is ready" email carrying the download link. The exporter is
faked so these tests need no Calibre install.
"""

import zipfile
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest

from silverfish_api.export_service import ExportService
from silverfish_api.export_store import ExportStore


class _FakeExporter:
    """Stands in for CalibreExporter: writes a tiny library tree at *dest*."""

    def __init__(self) -> None:
        self.exported_to: Path | None = None
        self.book_ids: object = "unset"

    def export(self, destination: Path, book_ids: object = None) -> object:
        self.exported_to = destination
        self.book_ids = book_ids
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "metadata.db").write_bytes(b"calibre db")
        book_dir = destination / "Stephen King" / "It (1)"
        book_dir.mkdir(parents=True)
        (book_dir / "It - Stephen King.epub").write_bytes(b"EPUBDATA")

        class _Result:
            book_count = 1

        return _Result()


def _clock() -> float:
    return 1000.0


@pytest.fixture
def store() -> ExportStore:
    return ExportStore(ttl_seconds=3600, clock=_clock)


@pytest.fixture
def service(tmp_path: Path, store: ExportStore) -> Iterator[ExportService]:
    exporter = _FakeExporter()
    yield ExportService(
        exporter=exporter,  # type: ignore[arg-type]
        store=store,
        work_dir=tmp_path / "work",
        download_base_url="/export/download",
    )


class TestRunExport:
    def test_returns_a_token(self, service: ExportService) -> None:
        result = service.run_export()
        assert result.token

    def test_zip_is_registered_and_resolvable(
        self, service: ExportService, store: ExportStore
    ) -> None:
        result = service.run_export()
        zip_path = store.resolve(result.token)
        assert zip_path is not None
        assert zip_path.exists()
        assert zipfile.is_zipfile(zip_path)

    def test_zip_contains_the_exported_library(
        self, service: ExportService, store: ExportStore
    ) -> None:
        result = service.run_export()
        zip_path = store.resolve(result.token)
        assert zip_path is not None
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any(n.endswith("metadata.db") for n in names)
        assert any(n.endswith("It - Stephen King.epub") for n in names)

    def test_intermediate_directory_is_removed(
        self, service: ExportService, tmp_path: Path
    ) -> None:
        service.run_export()
        # Only the zip should remain under the work dir, never the unzipped tree.
        work = tmp_path / "work"
        leftover_dirs = [p for p in work.rglob("*") if p.is_dir()]
        assert leftover_dirs == []

    def test_reports_book_count(self, service: ExportService) -> None:
        result = service.run_export()
        assert result.book_count == 1


class TestEmail:
    def test_builds_ready_email_with_link(self, service: ExportService) -> None:
        result = service.run_export()
        message = service.build_ready_email(to_email="me@example.com", token=result.token)
        assert isinstance(message, EmailMessage)
        assert message["To"] == "me@example.com"
        body = message.get_content()
        assert result.token in body
        assert "/export/download" in body
