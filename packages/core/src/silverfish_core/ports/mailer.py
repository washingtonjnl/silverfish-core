"""Port: sending email (e.g. send-to-Kindle).

Implemented by an SMTP adapter or a managed mailer. The core builds the message;
the adapter only transports it.
"""

from email.message import EmailMessage
from typing import Protocol, runtime_checkable


@runtime_checkable
class Mailer(Protocol):
    """Transport for outgoing email."""

    def send(self, message: EmailMessage) -> None:
        """Send a fully-built MIME *message*."""
        ...

    def test(self, recipient: str) -> None:
        """Send a connectivity test email to *recipient*."""
        ...
