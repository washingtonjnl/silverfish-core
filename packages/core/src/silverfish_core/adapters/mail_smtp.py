"""SMTP implementation of the ``Mailer`` port.

Transports a pre-built ``EmailMessage`` over SMTP. The transport (plain,
STARTTLS or implicit SSL), authentication and timeout come from ``SmtpSettings``;
the message itself is built by the caller (the core). The SMTP client classes
are injectable so tests can capture interactions without a real server.

Security: credentials live in the settings object (constructed once from config,
never passed per-request). They are never logged.
"""

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from enum import StrEnum
from typing import Protocol, cast

DEFAULT_TIMEOUT_SECONDS = 60.0


class SmtpSecurity(StrEnum):
    NONE = "none"
    STARTTLS = "starttls"
    SSL = "ssl"


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    """SMTP connection settings (built once from config)."""

    host: str
    port: int
    from_address: str
    username: str = ""
    password: str = ""
    security: SmtpSecurity = SmtpSecurity.STARTTLS
    timeout: float = DEFAULT_TIMEOUT_SECONDS


class _SmtpClient(Protocol):
    """The subset of smtplib.SMTP / SMTP_SSL this adapter uses."""

    def __enter__(self) -> "_SmtpClient": ...
    def __exit__(self, *args: object) -> None: ...
    def starttls(self, context: ssl.SSLContext | None = ...) -> object: ...
    def login(self, user: str, password: str) -> object: ...
    def send_message(self, message: EmailMessage) -> object: ...


SmtpFactory = Callable[..., _SmtpClient]


class SmtpMailer:
    """Send email via SMTP using the configured transport and credentials."""

    def __init__(
        self,
        *,
        settings: SmtpSettings,
        smtp_factory: SmtpFactory | None = None,
        smtp_ssl_factory: SmtpFactory | None = None,
    ) -> None:
        self._settings = settings
        # smtplib.SMTP/SMTP_SSL satisfy the client Protocol but their stubs are
        # broader than it, so cast the defaults to the factory type.
        self._smtp_factory: SmtpFactory = smtp_factory or cast("SmtpFactory", smtplib.SMTP)
        self._smtp_ssl_factory: SmtpFactory = smtp_ssl_factory or cast(
            "SmtpFactory", smtplib.SMTP_SSL
        )

    def send(self, message: EmailMessage) -> None:
        if not message["From"]:
            message["From"] = self._settings.from_address
        with self._connect() as client:
            if self._settings.security == SmtpSecurity.STARTTLS:
                client.starttls(context=ssl.create_default_context())
            if self._settings.password:
                client.login(self._settings.username, self._settings.password)
            client.send_message(message)

    def test(self, recipient: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Silverfish test email"
        message["To"] = recipient
        message["From"] = self._settings.from_address
        message.set_content("This is a test email from Silverfish. Your SMTP settings work.")
        self.send(message)

    def _connect(self) -> _SmtpClient:
        if self._settings.security == SmtpSecurity.SSL:
            return self._smtp_ssl_factory(
                self._settings.host, self._settings.port, timeout=self._settings.timeout
            )
        return self._smtp_factory(
            self._settings.host, self._settings.port, timeout=self._settings.timeout
        )
