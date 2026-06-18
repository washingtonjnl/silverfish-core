"""Tests for request input hardening (security audit follow-up).

Written before the implementation (TDD). Covers three confirmed findings from
the security audit, all about treating request input as hostile:

* Uploads have a configurable size ceiling, so a huge file can't exhaust memory
  (the route reads the body into RAM). Over the limit => 413, no full read.
* Email destinations are validated as real addresses (``EmailStr``), so a
  malformed value is rejected at the edge with 422 rather than reaching SMTP.
* Search filter lists are length-capped, so a query with tens of thousands of
  repeated params can't build a pathological query.
"""

import io
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from silverfish_api.app import create_app

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"
RICH_EPUB = CORE_TESTS / "fixtures" / "ebooks" / "rich.epub"


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
    # A tiny upload ceiling makes the limit cheap to exercise.
    monkeypatch.setenv("SILVERFISH_UPLOAD_MAX_MB", "1")
    with TestClient(create_app()) as test_client:
        yield test_client


class TestUploadSizeLimit:
    def test_rejects_oversized_upload_with_413(self, client: TestClient) -> None:
        # Two bytes over the 1 MiB ceiling.
        oversized = b"\0" * (1 * 1024 * 1024 + 2)
        response: Response = client.post(
            "/books",
            files={"file": ("big.epub", io.BytesIO(oversized), "application/epub+zip")},
        )
        assert response.status_code == 413
        assert response.json()["error"]["status"] == 413

    def test_accepts_upload_within_limit(self, client: TestClient) -> None:
        data = RICH_EPUB.read_bytes()
        assert len(data) < 1 * 1024 * 1024  # fixture is comfortably under the cap
        response = client.post(
            "/books", files={"file": ("rich.epub", io.BytesIO(data), "application/epub+zip")}
        )
        assert response.status_code == 201

    def test_413_documented_on_upload(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        responses = schema["paths"]["/books"]["post"]["responses"]
        assert "413" in responses


class TestEmailValidation:
    def test_send_rejects_malformed_email_with_422(self, client: TestClient) -> None:
        response = client.post("/books/1/send", json={"to_email": "not-an-email"})
        assert response.status_code == 422

    def test_export_rejects_malformed_email_with_422(self, client: TestClient) -> None:
        response = client.post("/export/calibre", json={"to_email": "   "})
        assert response.status_code == 422

    def test_email_test_rejects_malformed_email_with_422(self, client: TestClient) -> None:
        response = client.post("/config/email/test", json={"to_email": "bob@"})
        assert response.status_code == 422


class TestSearchFilterLimits:
    def test_rejects_too_many_filter_values_with_422(self, client: TestClient) -> None:
        # Far more include_tags than any real query — must be rejected, not run.
        too_many = [("include_tags", f"t{i}") for i in range(1000)]
        response = client.get("/search", params=too_many)
        assert response.status_code == 422

    def test_accepts_reasonable_filter_values(self, client: TestClient) -> None:
        response = client.get("/search", params=[("include_tags", "fiction"), ("languages", "eng")])
        assert response.status_code == 200
