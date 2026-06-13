"""Smoke tests for the API scaffolding.

These assert the minimal contract of the app factory: a health endpoint and a
generated OpenAPI document. They exist before the implementation (TDD) and gate
the scaffolding as green.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from silverfish_api import __version__
from silverfish_api.app import create_app


def test_create_app_returns_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    # Version is derived from the git tag, so assert it matches the package's
    # reported version rather than a hardcoded literal.
    assert response.json() == {"status": "ok", "version": __version__}


def test_openapi_contract_is_generated() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Silverfish API"
    assert "/health" in schema["paths"]
