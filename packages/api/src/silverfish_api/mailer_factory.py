"""Mailer factory — maps SMTP config to a Mailer, or ``None`` if unconfigured.

The reference API builds one global mailer at boot from env-provided SMTP
settings. A SaaS consumer can reuse the same factory per-request to build a
mailer from a user's own (encrypted, stored) credentials. Either way, the
credentials come from config — never from a send request.
"""

from silverfish_api.config import Settings
from silverfish_core.adapters.mail_smtp import SmtpMailer, SmtpSecurity, SmtpSettings


def build_mailer(settings: Settings) -> SmtpMailer | None:
    """Build the configured SMTP mailer, or ``None`` when SMTP is not set up."""
    if not settings.smtp_configured:
        return None
    smtp_settings = SmtpSettings(
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_address=settings.smtp_from or settings.smtp_username,
        username=settings.smtp_username,
        password=settings.smtp_password,
        security=_security(settings.smtp_security),
    )
    return SmtpMailer(settings=smtp_settings)


def _security(value: str) -> SmtpSecurity:
    try:
        return SmtpSecurity(value.lower())
    except ValueError:
        return SmtpSecurity.STARTTLS
