"""Tests for the cover and per-format download endpoints.

Written before the implementation (TDD). The API streams files via storage; it
never exposes filesystem paths. Uses a real Calibre library copy with the
fixture book files placed on disk.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"
RICH_EPUB = CORE_TESTS / "fixtures" / "ebooks" / "rich.epub"


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    # Place book 1's files on disk to match its DB path.
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    (book_dir / "The Great Book - Jane Austen.epub").write_bytes(b"EPUB-BYTES")
    (book_dir / "cover.jpg").write_bytes(b"\xff\xd8JPEGDATA")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    with TestClient(create_app()) as test_client:
        yield test_client


class TestCover:
    def test_returns_cover_bytes(self, client: TestClient) -> None:
        response = client.get("/books/1/cover")
        assert response.status_code == 200
        assert response.content == b"\xff\xd8JPEGDATA"
        assert response.headers["content-type"] == "image/jpeg"

    def test_404_when_no_cover(self, client: TestClient) -> None:
        # Book 2 has no cover file on disk / has_cover handling.
        response = client.get("/books/2/cover")
        assert response.status_code == 404

    def test_404_for_missing_book(self, client: TestClient) -> None:
        assert client.get("/books/999999/cover").status_code == 404


class TestSetCover:
    def test_sets_and_replaces_the_cover(self, client: TestClient) -> None:
        new = b"\xff\xd8NEW-COVER"
        res = client.put(
            "/books/1/cover",
            files={"file": ("c.jpg", new, "image/jpeg")},
        )
        assert res.status_code == 204
        # The cover now downloads as the new bytes.
        assert client.get("/books/1/cover").content == new

    def test_sets_cover_on_a_book_that_had_none(self, client: TestClient) -> None:
        # Book 2 has no cover; setting one makes it downloadable + marks has_cover.
        assert client.get("/books/2/cover").status_code == 404
        res = client.put(
            "/books/2/cover",
            files={"file": ("c.png", b"\x89PNG-DATA", "image/png")},
        )
        assert res.status_code == 204
        assert client.get("/books/2/cover").status_code == 200
        assert client.get("/books/2").json()["has_cover"] is True

    def test_rejects_a_non_image(self, client: TestClient) -> None:
        res = client.put(
            "/books/1/cover",
            files={"file": ("x.txt", b"not an image", "text/plain")},
        )
        assert res.status_code == 400

    def test_404_for_missing_book(self, client: TestClient) -> None:
        res = client.put(
            "/books/999999/cover",
            files={"file": ("c.jpg", b"\xff\xd8x", "image/jpeg")},
        )
        assert res.status_code == 404


class TestDownload:
    def test_downloads_format(self, client: TestClient) -> None:
        response = client.get("/books/1/formats/epub")
        assert response.status_code == 200
        assert response.content == b"EPUB-BYTES"

    def test_download_is_case_insensitive(self, client: TestClient) -> None:
        assert client.get("/books/1/formats/EPUB").status_code == 200

    def test_404_for_missing_format(self, client: TestClient) -> None:
        assert client.get("/books/1/formats/mobi").status_code == 404

    def test_404_for_missing_book(self, client: TestClient) -> None:
        assert client.get("/books/999999/formats/epub").status_code == 404

    def test_sets_attachment_filename(self, client: TestClient) -> None:
        response = client.get("/books/1/formats/epub")
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert ".epub" in disposition


class TestDeleteFormat:
    def test_deletes_format_file_and_record(self, client: TestClient, library: Path) -> None:
        epub = library / "Jane Austen" / "The Great Book (1)" / "The Great Book - Jane Austen.epub"
        assert epub.exists()

        response = client.delete("/books/1/formats/epub")
        assert response.status_code == 204
        assert not epub.exists()
        # The format no longer downloads, but the book still exists.
        assert client.get("/books/1/formats/epub").status_code == 404
        assert client.get("/books/1").status_code == 200

    def test_404_for_missing_format(self, client: TestClient) -> None:
        assert client.delete("/books/1/formats/mobi").status_code == 404

    def test_404_for_missing_book(self, client: TestClient) -> None:
        assert client.delete("/books/999999/formats/epub").status_code == 404


class TestOpenAPI:
    def test_endpoints_documented(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "/books/{book_id}/cover" in schema["paths"]
        assert "put" in schema["paths"]["/books/{book_id}/cover"]
        assert "/books/{book_id}/formats/{book_format}" in schema["paths"]
        assert "delete" in schema["paths"]["/books/{book_id}/formats/{book_format}"]
