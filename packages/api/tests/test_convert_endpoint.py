"""Tests for the async conversion endpoint and job status.

Written before the implementation (TDD). POST enqueues a conversion job and
returns immediately with a job id; GET /jobs/{id} reports progress until done.
Uses a real Calibre library copy and the real ebook-convert binary (skipped when
not installed).
"""

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_core.adapters.calibre_binaries import CalibreBinaries

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"
MINIMAL_EPUB = CORE_TESTS / "fixtures" / "ebooks" / "minimal.epub"

_HAS_CONVERT = CalibreBinaries().ebook_convert is not None
pytestmark = pytest.mark.skipif(not _HAS_CONVERT, reason="ebook-convert not installed")


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    # Place book 1's EPUB (a real, convertible file) on disk.
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    shutil.copy(MINIMAL_EPUB, book_dir / "The Great Book - Jane Austen.epub")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    with TestClient(create_app()) as test_client:
        yield test_client


def _wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(f"/jobs/{job_id}").json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.1)
    msg = "job did not finish in time"
    raise AssertionError(msg)


class TestConvert:
    def test_enqueues_job_and_completes(self, client: TestClient, library: Path) -> None:
        response = client.post(
            "/books/1/convert", json={"source_format": "EPUB", "target_format": "PDF"}
        )
        assert response.status_code == 202
        job = response.json()
        assert job["status"] in {"queued", "running"}

        final = _wait_done(client, job["id"])
        assert final["status"] == "done"
        # The new format file exists on disk.
        assert (
            library / "Jane Austen" / "The Great Book (1)" / "The Great Book - Jane Austen.pdf"
        ).exists()

    def test_converted_format_is_registered(self, client: TestClient) -> None:
        job = client.post(
            "/books/1/convert", json={"source_format": "EPUB", "target_format": "PDF"}
        ).json()
        _wait_done(client, job["id"])
        formats = {f["extension"] for f in client.get("/books/1").json()["formats"]}
        assert "PDF" in formats

    def test_404_for_missing_book(self, client: TestClient) -> None:
        response = client.post(
            "/books/999999/convert", json={"source_format": "EPUB", "target_format": "PDF"}
        )
        assert response.status_code == 404


class TestJobStatus:
    def test_unknown_job_is_404(self, client: TestClient) -> None:
        assert client.get("/jobs/does-not-exist").status_code == 404
