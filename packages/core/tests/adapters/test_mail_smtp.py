"""Tests for the SMTP mailer adapter.

Written before the implementation (TDD). The adapter transports a pre-built
EmailMessage over SMTP, choosing plain/STARTTLS/SSL from config and
authenticating when a password is set. A fake SMTP transport captures what would
be sent, so no real server is needed.
"""

from email.message import EmailMessage
from typing import ClassVar

import pytest

from silverfish_core.adapters.mail_smtp import SmtpMailer, SmtpSettings
from silverfish_core.ports import Mailer


class FakeSmtp:
    """Records the SMTP interactions a real client would perform."""

    instances: ClassVar[list["FakeSmtp"]] = []

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: EmailMessage | None = None
        self.quit_called = False
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        self.quit_called = True

    def starttls(self, context: object = None) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent = message


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeSmtp.instances.clear()


def _settings(**overrides: object) -> SmtpSettings:
    base: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "me@example.com",
        "password": "secret",
        "from_address": "me@example.com",
        "security": "starttls",
    }
    base.update(overrides)
    return SmtpSettings(**base)  # type: ignore[arg-type]


def _mailer(settings: SmtpSettings) -> SmtpMailer:
    return SmtpMailer(settings=settings, smtp_factory=FakeSmtp, smtp_ssl_factory=FakeSmtp)


def _message() -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your book"
    msg["To"] = "kindle@kindle.com"
    msg.set_content("here is your book")
    return msg


class TestConformance:
    def test_is_a_mailer(self) -> None:
        assert isinstance(_mailer(_settings()), Mailer)


class TestSend:
    def test_sends_the_message(self) -> None:
        _mailer(_settings()).send(_message())
        smtp = FakeSmtp.instances[-1]
        assert smtp.sent is not None
        assert smtp.sent["Subject"] == "Your book"

    def test_sets_from_when_missing(self) -> None:
        msg = _message()
        _mailer(_settings(from_address="library@me.com")).send(msg)
        smtp = FakeSmtp.instances[-1]
        assert smtp.sent is not None
        assert smtp.sent["From"] == "library@me.com"

    def test_starttls_security_starts_tls(self) -> None:
        _mailer(_settings(security="starttls")).send(_message())
        assert FakeSmtp.instances[-1].started_tls is True

    def test_plain_security_does_not_start_tls(self) -> None:
        _mailer(_settings(security="none", password="")).send(_message())
        assert FakeSmtp.instances[-1].started_tls is False

    def test_authenticates_when_password_set(self) -> None:
        _mailer(_settings(username="u", password="p")).send(_message())
        assert FakeSmtp.instances[-1].logged_in == ("u", "p")

    def test_does_not_authenticate_without_password(self) -> None:
        _mailer(_settings(password="", security="none")).send(_message())
        assert FakeSmtp.instances[-1].logged_in is None

    def test_uses_configured_host_and_port(self) -> None:
        _mailer(_settings(host="mail.local", port=2525)).send(_message())
        smtp = FakeSmtp.instances[-1]
        assert (smtp.host, smtp.port) == ("mail.local", 2525)


class TestTest:
    def test_sends_a_connectivity_email(self) -> None:
        _mailer(_settings()).test("admin@example.com")
        smtp = FakeSmtp.instances[-1]
        assert smtp.sent is not None
        assert smtp.sent["To"] == "admin@example.com"
