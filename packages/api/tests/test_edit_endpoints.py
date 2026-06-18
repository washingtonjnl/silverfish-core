"""Tests for the metadata edit (PATCH) and delete (DELETE) endpoints.

Written before the implementation (TDD). PATCH applies a partial update onto the
existing book; renaming title/author moves the folder on disk. DELETE removes
the book and its folder. Uses a real Calibre library copy with files on disk.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app

FIXTURE_DB = (
    Path(__file__).parents[2] / "core" / "tests" / "fixtures" / "calibre_library" / "metadata.db"
)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    # Book 1: "Jane Austen/The Great Book (1)" with a file on disk.
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    (book_dir / "The Great Book - Jane Austen.epub").write_bytes(b"DATA")
    (book_dir / "cover.jpg").write_bytes(b"\xff\xd8")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    with TestClient(create_app()) as test_client:
        yield test_client


class TestPatch:
    def test_updates_title(self, client: TestClient) -> None:
        response = client.patch("/books/1", json={"title": "A Renamed Book"})
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "A Renamed Book"
        assert body["sort"] == "Renamed Book, A"

    def test_updates_rating(self, client: TestClient) -> None:
        response = client.patch("/books/1", json={"rating": 4})
        assert response.json()["rating"] == 4

    def test_updates_tags(self, client: TestClient) -> None:
        response = client.patch("/books/1", json={"tags": ["x", "y"]})
        assert {t["name"] for t in response.json()["tags"]} == {"x", "y"}

    def test_partial_update_keeps_other_fields(self, client: TestClient) -> None:
        # Only change rating; title stays.
        client.patch("/books/1", json={"rating": 7})
        assert client.get("/books/1").json()["title"] == "The Great Book"

    def test_rename_moves_folder_on_disk(self, client: TestClient, library: Path) -> None:
        client.patch("/books/1", json={"title": "Moved Title"})
        assert not (library / "Jane Austen" / "The Great Book (1)").exists()
        moved = library / "Jane Austen" / "Moved Title (1)"
        assert (moved / "The Great Book - Jane Austen.epub").exists()

    def test_404_for_missing_book(self, client: TestClient) -> None:
        assert client.patch("/books/999999", json={"title": "x"}).status_code == 404

    def test_empty_patch_is_bad_request(self, client: TestClient) -> None:
        response = client.patch("/books/1", json={})
        assert response.status_code == 400
        assert response.json()["error"]["status"] == 400

    def test_empty_patch_does_not_modify_book(self, client: TestClient) -> None:
        client.patch("/books/1", json={})
        assert client.get("/books/1").json()["title"] == "The Great Book"

    @pytest.mark.parametrize("bad_rating", [11, 123, -1])
    def test_out_of_range_rating_is_rejected_not_500(
        self, client: TestClient, bad_rating: int
    ) -> None:
        response = client.patch("/books/1", json={"rating": bad_rating})
        # Schema bound -> 422; must never be a 500 that breaks the API.
        assert response.status_code == 422

    def test_out_of_range_rating_does_not_modify_book(self, client: TestClient) -> None:
        client.patch("/books/1", json={"rating": 999})
        assert client.get("/books/1").json()["rating"] == 6  # fixture's original


class TestDelete:
    def test_deletes_book(self, client: TestClient) -> None:
        assert client.delete("/books/1").status_code == 204
        assert client.get("/books/1").status_code == 404

    def test_removes_folder(self, client: TestClient, library: Path) -> None:
        client.delete("/books/1")
        assert not (library / "Jane Austen" / "The Great Book (1)").exists()

    def test_delete_missing_is_404(self, client: TestClient) -> None:
        assert client.delete("/books/999999").status_code == 404


class TestOpenAPI:
    def test_documented(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "patch" in schema["paths"]["/books/{book_id}"]
        assert "delete" in schema["paths"]["/books/{book_id}"]
