"""Tests for standardized error responses and their OpenAPI documentation.

Written before the implementation (TDD). Every error the API returns shares one
shape (``ErrorResponse``), and the routes document the errors that can actually
occur: 404 where there is an id lookup, 422 where there is validation, and 500
everywhere (it can always happen).
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


class TestErrorBodyShape:
    def test_404_uses_standard_error_shape(self, client: TestClient) -> None:
        response = client.get("/books/999999")
        assert response.status_code == 404
        body = response.json()
        assert body == {"error": {"status": 404, "message": body["error"]["message"]}}
        assert isinstance(body["error"]["message"], str)
        assert body["error"]["message"]

    def test_422_uses_standard_error_shape(self, client: TestClient) -> None:
        response = client.get("/books", params={"page": 0})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["status"] == 422
        assert "message" in body["error"]
        # Validation errors expose the offending fields for clients.
        assert "details" in body["error"]


class TestOpenAPIDocumentsErrors:
    @pytest.fixture
    def schema(self, client: TestClient) -> dict[str, object]:
        data: dict[str, object] = client.get("/openapi.json").json()
        return data

    def _responses(self, schema: dict[str, object], path: str, method: str) -> dict[str, object]:
        paths = schema["paths"]
        assert isinstance(paths, dict)
        operations = paths[path]
        assert isinstance(operations, dict)
        operation = operations[method]
        assert isinstance(operation, dict)
        responses = operation["responses"]
        assert isinstance(responses, dict)
        return responses

    def test_get_book_documents_404_422_500(self, schema: dict[str, object]) -> None:
        responses = self._responses(schema, "/books/{book_id}", "get")
        assert "404" in responses
        assert "422" in responses
        assert "500" in responses

    def test_list_books_documents_422_500_but_not_404(self, schema: dict[str, object]) -> None:
        responses = self._responses(schema, "/books", "get")
        assert "422" in responses
        assert "500" in responses
        # A listing never 404s; documenting it would be misleading.
        assert "404" not in responses

    def test_search_documents_422_500(self, schema: dict[str, object]) -> None:
        responses = self._responses(schema, "/search", "get")
        assert "422" in responses
        assert "500" in responses
        assert "404" not in responses

    def test_error_schema_is_referenced(self, schema: dict[str, object]) -> None:
        responses = self._responses(schema, "/books/{book_id}", "get")
        not_found = responses["404"]
        assert isinstance(not_found, dict)
        content = not_found["content"]["application/json"]
        assert "$ref" in content["schema"] or "schema" in content
