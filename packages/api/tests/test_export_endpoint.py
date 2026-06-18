"""Tests for the Calibre export endpoints (TDD).

POST /export/calibre starts an async job that snapshots the library to a zip and
emails a time-limited download link; it never holds the connection while the
(potentially large) export runs. GET /export/download/{token} streams the zip
back and 404s for an unknown or expired token. Calibre/SMTP are faked so the
test needs neither installed.
"""

from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_api.export_service import ExportService
from silverfish_api.export_store import ExportStore


class _FakeMailer:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def test(self, recipient: str) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


class _FakeExporter:
    """Writes a tiny Calibre-looking tree, so the service can zip it without
    needing a real calibredb (the binary is unavailable/locked in CI)."""

    def export(self, destination: Path) -> object:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "metadata.db").write_bytes(b"calibre db")

        class _Result:
            book_count = 0

        return _Result()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Standalone mode with a fresh library and SMTP "configured" so export is
    # available; the real mailer is swapped for a fake after startup.
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(tmp_path / "lib"))
    monkeypatch.setenv("SILVERFISH_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SILVERFISH_SMTP_FROM", "library@example.com")
    monkeypatch.setenv("SILVERFISH_PUBLIC_BASE_URL", "http://localhost:8000")
    app = create_app()
    with TestClient(app) as test_client:
        state = test_client.app.state  # type: ignore[attr-defined]
        state.mailer = _FakeMailer()
        # Swap in a service backed by a fake exporter so the test never needs a
        # real (possibly locked) calibredb; the store/zip/email path is real.
        store = ExportStore(ttl_seconds=3600, clock=__import__("time").time)
        state.export_store = store
        state.export_service = ExportService(
            exporter=_FakeExporter(),  # type: ignore[arg-type]
            store=store,
            work_dir=tmp_path / "work",
            download_base_url="http://localhost:8000/export/download",
        )
        yield test_client


def _wait_done(client: TestClient, job_id: str) -> dict[str, object]:
    # The in-process worker runs concurrently; poll the job to completion.
    import time

    for _ in range(100):
        body: dict[str, object] = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        # A short sleep keeps the test from busy-spinning the GIL.
        time.sleep(0.02)
    raise AssertionError("export job did not finish in time")


class TestStartExport:
    def test_returns_202_with_job(self, client: TestClient) -> None:
        response = client.post("/export/calibre", json={"to_email": "me@example.com"})
        assert response.status_code == 202
        assert response.json()["type"] == "export"

    def test_requires_smtp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # No SMTP configured -> export delivery is unavailable.
        monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(tmp_path / "lib2"))
        monkeypatch.delenv("SILVERFISH_SMTP_HOST", raising=False)
        with TestClient(create_app()) as bare:
            response = bare.post("/export/calibre", json={"to_email": "me@example.com"})
        assert response.status_code == 503

    def test_requires_public_base_url(self, client: TestClient) -> None:
        # SMTP and calibredb are fine, but the link would be relative without a
        # public base URL: refuse with a clear 503 instead of mailing a dud link.
        service = client.app.state.export_service  # type: ignore[attr-defined]
        # Re-point the service at a relative base URL to simulate the missing var.
        object.__setattr__(service, "_download_base_url", "/export/download")
        response = client.post("/export/calibre", json={"to_email": "me@example.com"})
        assert response.status_code == 503
        assert "SILVERFISH_PUBLIC_BASE_URL" in response.json()["error"]["message"]


class TestDownload:
    def test_unknown_token_is_404(self, client: TestClient) -> None:
        assert client.get("/export/download/nope").status_code == 404

    def test_full_flow_emails_link_and_serves_zip(self, client: TestClient) -> None:
        # Start the export and wait for the async job to finish.
        start = client.post("/export/calibre", json={"to_email": "me@example.com"})
        job_id = start.json()["id"]
        done = _wait_done(client, job_id)
        assert done["status"] == "done", done

        # The link was emailed (never the zip itself) and is an absolute URL.
        mailer = client.app.state.mailer  # type: ignore[attr-defined]
        assert len(mailer.sent) == 1
        body = mailer.sent[0].get_content()
        assert "http://localhost:8000/export/download/" in body
        token = body.rsplit("/export/download/", 1)[1].split()[0].strip()

        # The emailed link downloads the zip.
        response = client.get(f"/export/download/{token}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.content[:2] == b"PK"  # zip magic
