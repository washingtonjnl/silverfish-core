"""Tests for the write-metadata endpoint.

Written before the implementation (TDD). POST spawns one background job per
format the book has and returns them immediately; each job embeds that format's
metadata via the WriteMetadataService. The orchestration (one job per format,
dedup, error mapping) is tested with a fake service injected on app state, so it
runs without the real ebook-meta binary. A 503 path is covered by clearing the
service.
"""

import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_core.services.write_metadata import WriteMetadataService

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"
MINIMAL_EPUB = CORE_TESTS / "fixtures" / "ebooks" / "minimal.epub"


class _FakeWriteService(WriteMetadataService):
    """Records each per-format write and reports progress, never touching disk.

    Subclasses the real service (without calling its ``__init__``) so it passes
    the app's ``isinstance`` dependency check while needing no ebook-meta binary.
    """

    def __init__(self, *, fail_formats: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._fail = fail_formats or set()

    def write_format(
        self,
        *,
        book_id: int,
        book_format: str,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> None:
        self.calls.append(book_format)
        if on_progress is not None:
            on_progress(0.0, "start")
        if book_format in self._fail:
            msg = f"could not write {book_format}"
            raise RuntimeError(msg)
        if on_progress is not None:
            on_progress(1.0, "done")


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    # Book 1 in the fixture has a single EPUB format registered.
    shutil.copy(MINIMAL_EPUB, book_dir / "The Great Book - Jane Austen.epub")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    with TestClient(create_app()) as test_client:
        # Inject a fake so the endpoint runs without ebook-meta installed.
        test_client.app.state.write_metadata_service = _FakeWriteService()  # type: ignore[attr-defined]
        yield test_client


def _wait_done(client: TestClient, job_id: str, timeout: float = 10.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(f"/jobs/{job_id}").json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.02)
    msg = "job did not finish in time"
    raise AssertionError(msg)


class TestWriteMetadata:
    def test_returns_202_with_one_job_per_format(self, client: TestClient) -> None:
        response = client.post("/books/1/write-metadata")
        assert response.status_code == 202
        body = response.json()
        # Book 1 has exactly one format (EPUB) in the fixture.
        assert [entry["format"] for entry in body["jobs"]] == ["EPUB"]
        assert body["jobs"][0]["job"]["type"] == "write_metadata"

    def test_job_completes_and_invokes_the_service(self, client: TestClient) -> None:
        body = client.post("/books/1/write-metadata").json()
        job_id = body["jobs"][0]["job"]["id"]
        final = _wait_done(client, job_id)
        assert final["status"] == "done"
        service = client.app.state.write_metadata_service  # type: ignore[attr-defined]
        assert service.calls == ["EPUB"]

    def test_service_failure_ends_job_in_error(self, client: TestClient) -> None:
        client.app.state.write_metadata_service = _FakeWriteService(fail_formats={"EPUB"})  # type: ignore[attr-defined]
        body = client.post("/books/1/write-metadata").json()
        final = _wait_done(client, body["jobs"][0]["job"]["id"])
        assert final["status"] == "error"
        assert "EPUB" in str(final["error"])

    def test_404_for_missing_book(self, client: TestClient) -> None:
        assert client.post("/books/999999/write-metadata").status_code == 404

    def test_503_when_service_unavailable(self, client: TestClient) -> None:
        client.app.state.write_metadata_service = None  # type: ignore[attr-defined]
        assert client.post("/books/1/write-metadata").status_code == 503

    def test_duplicate_in_flight_format_is_not_doubled(self, client: TestClient) -> None:
        # Make the write block long enough that the second request sees the first
        # still active, so it reuses that job rather than spawning a second.
        class _SlowService(WriteMetadataService):
            def __init__(self) -> None:
                self.calls = 0

            def write_format(
                self,
                *,
                book_id: int,
                book_format: str,
                on_progress: Callable[[float, str], None] | None = None,
            ) -> None:
                self.calls += 1
                time.sleep(0.3)

        slow = _SlowService()
        client.app.state.write_metadata_service = slow  # type: ignore[attr-defined]
        first = client.post("/books/1/write-metadata").json()
        second = client.post("/books/1/write-metadata").json()
        assert first["jobs"][0]["job"]["id"] == second["jobs"][0]["job"]["id"]
