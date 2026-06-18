"""Tests for the upload endpoint (POST /books).

Written before the implementation (TDD). Uploads an EPUB into a real Calibre
library copy and asserts the book is created (readable via GET) and the file
landed under the library directory.
"""

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
    with TestClient(create_app()) as test_client:
        yield test_client


def _upload(client: TestClient, name: str = "rich.epub") -> Response:
    data = RICH_EPUB.read_bytes()
    response: Response = client.post("/books", files={"file": (name, data, "application/epub+zip")})
    return response


class TestUpload:
    def test_upload_creates_book(self, client: TestClient) -> None:
        response = _upload(client)
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "The Hobbit"
        assert [a["name"] for a in body["authors"]] == ["J. R. R. Tolkien"]
        # The public id is a non-empty base62 string.
        assert isinstance(body["id"], str)
        assert body["id"]

    def test_uploaded_book_is_listed(self, client: TestClient) -> None:
        _upload(client)
        listing = client.get("/books").json()
        titles = {b["title"] for b in listing["items"]}
        assert "The Hobbit" in titles
        assert listing["total"] == 4  # 3 fixtures + 1 uploaded

    def test_uploaded_book_readable_by_id(self, client: TestClient) -> None:
        created = _upload(client).json()
        fetched = client.get(f"/books/{created['id']}").json()
        assert fetched["title"] == "The Hobbit"
        assert fetched["series"]["name"] == "Middle-earth"

    def test_file_lands_in_library(self, client: TestClient, library: Path) -> None:
        created = _upload(client).json()
        book_dir = library / "J. R. R. Tolkien" / f"The Hobbit ({created['id']})"
        files = list(book_dir.glob("*.epub"))
        assert len(files) == 1
        assert (book_dir / "cover.jpg").exists()

    def test_rejects_missing_file(self, client: TestClient) -> None:
        response = client.post("/books")
        assert response.status_code == 422

    def test_rejects_disallowed_extension(self, client: TestClient) -> None:
        response = client.post(
            "/books", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}
        )
        assert response.status_code == 400
        assert response.json()["error"]["status"] == 400


class TestOpenAPI:
    def test_post_books_documented(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "post" in schema["paths"]["/books"]
        responses = schema["paths"]["/books"]["post"]["responses"]
        assert "201" in responses
        assert "400" in responses
