"""Tests guarding the quality of the generated OpenAPI contract.

The OpenAPI document is the source the SDKs are generated from, so its quality is
the SDK's quality. These tests pin the things that matter for a clean generated
client: readable operation ids (→ method names), enum-typed status fields (→
type-safe unions), and a documented error model.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from silverfish_api.app import create_app


@pytest.fixture
def spec() -> Iterator[dict[str, Any]]:
    # Build the app from a clean cwd so it doesn't read a developer's .env.local.
    for key in [k for k in os.environ if k.startswith("SILVERFISH_")]:
        del os.environ[key]
    old = Path.cwd()
    os.chdir(tempfile.mkdtemp())
    try:
        yield create_app().openapi()
    finally:
        os.chdir(old)


def _operation_ids(spec: dict[str, Any]) -> list[str]:
    return [
        op["operationId"]
        for methods in spec["paths"].values()
        for op in methods.values()
        if "operationId" in op
    ]


class TestOperationIds:
    def test_are_clean_without_path_noise(self, spec: dict[str, Any]) -> None:
        # FastAPI's default ids look like 'get_book_books__book_id__get'; a clean
        # contract uses the function name only (e.g. 'get_book'), so SDK
        # generators produce good method names. Assert no id carries the
        # route/verb noise.
        for op_id in _operation_ids(spec):
            assert "__" not in op_id, op_id
            assert not op_id.endswith(("_get", "_post", "_patch", "_delete")), op_id

    def test_operation_ids_are_unique(self, spec: dict[str, Any]) -> None:
        ids = _operation_ids(spec)
        assert len(ids) == len(set(ids))

    def test_known_operations_have_expected_ids(self, spec: dict[str, Any]) -> None:
        # snake_case, matching the route function names (SDK generators re-case).
        ids = set(_operation_ids(spec))
        assert "upload_book" in ids
        assert "get_book" in ids
        assert "start_export" in ids


class TestTypedStatusFields:
    def test_job_status_is_an_enum(self, spec: dict[str, Any]) -> None:
        job = spec["components"]["schemas"]["JobOut"]
        status = job["properties"]["status"]
        # An enum (directly or via $ref), not a bare string.
        assert "enum" in status or "$ref" in status or "allOf" in status

    def test_job_type_is_an_enum(self, spec: dict[str, Any]) -> None:
        job = spec["components"]["schemas"]["JobOut"]
        job_type = job["properties"]["type"]
        assert "enum" in job_type or "$ref" in job_type or "allOf" in job_type


class TestErrorModel:
    def test_error_response_schema_is_present(self, spec: dict[str, Any]) -> None:
        assert "ErrorResponse" in spec["components"]["schemas"]

    def test_a_4xx_documents_the_error_schema(self, spec: dict[str, Any]) -> None:
        get_book = spec["paths"]["/books/{book_id}"]["get"]
        not_found = get_book["responses"]["404"]
        content = not_found.get("content", {})
        assert "application/json" in content
