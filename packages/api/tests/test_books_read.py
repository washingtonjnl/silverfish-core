"""Tests for the read-side book endpoints.

Written before the implementation (TDD). The app is wired to a real Calibre
``metadata.db`` fixture via the ``SILVERFISH_LIBRARY_DIR`` env var, exercising
the full HTTP -> service -> repository path against actual data.
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
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    library = tmp_path / "library"
    library.mkdir()
    shutil.copy(FIXTURE_DB, library / "metadata.db")
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    with TestClient(create_app()) as test_client:
        yield test_client


class TestListBooks:
    def test_lists_all_books(self, client: TestClient) -> None:
        response = client.get("/books")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    def test_pagination_params(self, client: TestClient) -> None:
        response = client.get("/books", params={"page": 1, "page_size": 2})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["has_next"] is True

    def test_item_shape(self, client: TestClient) -> None:
        response = client.get("/books")
        item = response.json()["items"][0]
        assert {"id", "title", "authors", "tags", "rating"} <= set(item)

    def test_rejects_invalid_page(self, client: TestClient) -> None:
        assert client.get("/books", params={"page": 0}).status_code == 422


class TestGetBook:
    def test_returns_book(self, client: TestClient) -> None:
        response = client.get("/books/1")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 1
        assert body["title"] == "The Great Book"
        assert body["rating"] == 6
        assert [a["name"] for a in body["authors"]] == ["Jane Austen"]

    def test_missing_book_is_404(self, client: TestClient) -> None:
        assert client.get("/books/999").status_code == 404


class TestSearch:
    def test_search_by_term(self, client: TestClient) -> None:
        response = client.get("/search", params={"q": "Dune"})
        assert response.status_code == 200
        titles = {b["title"] for b in response.json()["items"]}
        assert titles == {"Dune"}

    def test_search_include_tag_filter(self, client: TestClient) -> None:
        response = client.get("/search", params={"q": "", "include_tags": "sci-fi"})
        assert response.status_code == 200
        titles = {b["title"] for b in response.json()["items"]}
        assert titles == {"Dune"}


class TestOpenAPIContract:
    def test_book_endpoints_in_schema(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "/books" in schema["paths"]
        assert "/books/{book_id}" in schema["paths"]
        assert "/search" in schema["paths"]
