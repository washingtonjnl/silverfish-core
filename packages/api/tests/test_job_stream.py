"""Tests for the SSE job-status stream.

Written before the implementation (TDD). GET /jobs/{id}/stream pushes the job's
status and progress as Server-Sent Events until it reaches a terminal state, so
clients follow progress without repeated polling.
"""

import json
import shutil
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


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    shutil.copy(MINIMAL_EPUB, book_dir / "The Great Book - Jane Austen.epub")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    with TestClient(create_app()) as test_client:
        yield test_client


def _parse_events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


class TestStream:
    def test_unknown_job_is_404(self, client: TestClient) -> None:
        assert client.get("/jobs/nope/stream").status_code == 404

    @pytest.mark.skipif(not _HAS_CONVERT, reason="ebook-convert not installed")
    def test_streams_until_done(self, client: TestClient) -> None:
        job = client.post(
            "/books/1/convert", json={"source_format": "EPUB", "target_format": "PDF"}
        ).json()

        response = client.get(f"/jobs/{job['id']}/stream")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = _parse_events(response.text)
        assert events  # at least one event
        assert events[-1]["status"] == "done"
        assert events[-1]["progress"] == 1.0
