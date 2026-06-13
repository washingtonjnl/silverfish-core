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
    # `with` runs the lifespan, which builds app state (incl. binary discovery).
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Version is derived from the git tag, not a hardcoded literal.
    assert body["version"] == __version__
    # Binary availability is reported so misconfiguration is visible.
    assert "convert_available" in body["binaries"]
    assert "metadata_available" in body["binaries"]


def test_openapi_contract_is_generated() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Silverfish API"
    assert "/health" in schema["paths"]
