"""Tests for the send endpoint and email-config routes.

Written before the implementation (TDD). Send enqueues a job (202); it validates
the book, SMTP availability and the requested/available format. A fake mailer is
injected so the SMTP transport is captured in-process (no network, no external
mail). SMTP-unconfigured cases boot the app without SMTP env.
"""

import shutil
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_core.services.send_to_ereader import SendToEreaderService

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.tested: list[str] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def test(self, recipient: str) -> None:
        self.tested.append(recipient)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    (book_dir / "The Great Book - Jane Austen.epub").write_bytes(b"EPUBDATA")
    return lib


@pytest.fixture
def configured(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, FakeMailer]]:
    """A client whose mailer + send service use an in-process FakeMailer."""
    # Run from a clean dir so the developer's real .env.local is not read.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    mailer = FakeMailer()
    app = create_app()

    with TestClient(app) as client:
        # Swap in the fake mailer and a send service wired to it.
        app.state.mailer = mailer
        app.state.send_service = SendToEreaderService(
            repository=app.state.repository, storage=app.state.storage, mailer=mailer
        )
        yield client, mailer


@pytest.fixture
def unconfigured(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A client without SMTP (mailer/send service are None)."""
    # Clean dir + cleared env so no .env.local provides SMTP config.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    monkeypatch.delenv("SILVERFISH_SMTP_HOST", raising=False)
    with TestClient(create_app()) as client:
        yield client


def _wait_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict[str, object]:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(f"/jobs/{job_id}").json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.05)
    msg = "job did not finish"
    raise AssertionError(msg)


class TestSend:
    def test_sends_book_and_completes(self, configured: tuple[TestClient, FakeMailer]) -> None:
        client, mailer = configured
        response = client.post("/books/1/send", json={"to_email": "me@kindle.com"})
        assert response.status_code == 202
        final = _wait_job(client, response.json()["id"])
        assert final["status"] == "done"
        assert len(mailer.sent) == 1
        assert mailer.sent[0]["To"] == "me@kindle.com"
        assert len(list(mailer.sent[0].iter_attachments())) == 1

    def test_503_when_smtp_unconfigured(self, unconfigured: TestClient) -> None:
        response = unconfigured.post("/books/1/send", json={"to_email": "me@kindle.com"})
        assert response.status_code == 503

    def test_404_for_missing_book(self, configured: tuple[TestClient, FakeMailer]) -> None:
        client, _ = configured
        response = client.post("/books/999999/send", json={"to_email": "me@kindle.com"})
        assert response.status_code == 404

    def test_400_for_unavailable_format(self, configured: tuple[TestClient, FakeMailer]) -> None:
        client, _ = configured
        response = client.post(
            "/books/1/send", json={"to_email": "me@kindle.com", "format": "mobi"}
        )
        assert response.status_code == 400

    def test_explicit_available_format_works(
        self, configured: tuple[TestClient, FakeMailer]
    ) -> None:
        client, mailer = configured
        response = client.post(
            "/books/1/send", json={"to_email": "me@kindle.com", "format": "epub"}
        )
        assert response.status_code == 202
        _wait_job(client, response.json()["id"])
        assert len(mailer.sent) == 1


class TestEmailConfig:
    def test_health_reports_send_unavailable(self, unconfigured: TestClient) -> None:
        body = unconfigured.get("/health").json()
        assert body["send_available"] is False

    def test_health_reports_send_available(self, configured: tuple[TestClient, FakeMailer]) -> None:
        client, _ = configured
        # The fake mailer was swapped onto app state, so send is available.
        assert client.get("/health").json()["send_available"] is True

    def test_config_email_returns_details_without_password(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SILVERFISH_SMTP_PORT", "2525")
        monkeypatch.setenv("SILVERFISH_SMTP_PASSWORD", "supersecret")
        with TestClient(create_app()) as client:
            body = client.get("/config/email").json()
        assert body["configured"] is True
        assert body["host"] == "smtp.example.com"
        assert body["port"] == 2525
        assert "password" not in body
        assert "supersecret" not in str(body)

    def test_test_email_sends(self, configured: tuple[TestClient, FakeMailer]) -> None:
        client, mailer = configured
        response = client.post("/config/email/test", json={"to_email": "admin@example.com"})
        assert response.status_code == 204
        assert mailer.tested == ["admin@example.com"]

    def test_test_email_503_when_unconfigured(self, unconfigured: TestClient) -> None:
        response = unconfigured.post("/config/email/test", json={"to_email": "a@b.com"})
        assert response.status_code == 503
