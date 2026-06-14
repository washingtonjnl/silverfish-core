"""Tests for SMTP settings loading and the mailer factory.

Written before the implementation (TDD). SMTP is configured by env; the factory
builds a mailer from it, or returns None when unconfigured (so the API can
report sending as unavailable).
"""

from pathlib import Path

import pytest

from silverfish_api.config import load_settings
from silverfish_api.mailer_factory import build_mailer
from silverfish_core.adapters.mail_smtp import SmtpMailer, SmtpSecurity


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SILVERFISH_SMTP_HOST",
        "SILVERFISH_SMTP_PORT",
        "SILVERFISH_SMTP_USERNAME",
        "SILVERFISH_SMTP_PASSWORD",
        "SILVERFISH_SMTP_FROM",
        "SILVERFISH_SMTP_SECURITY",
    ):
        monkeypatch.delenv(key, raising=False)


class TestSettings:
    def test_smtp_unconfigured_by_default(self, tmp_path: Path) -> None:
        settings = load_settings(env_dir=tmp_path)
        assert settings.smtp_configured is False

    def test_reads_smtp_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SILVERFISH_SMTP_PORT", "465")
        monkeypatch.setenv("SILVERFISH_SMTP_SECURITY", "ssl")
        settings = load_settings(env_dir=tmp_path)
        assert settings.smtp_configured is True
        assert settings.smtp_host == "smtp.example.com"
        assert settings.smtp_port == 465


class TestFactory:
    def test_returns_none_when_unconfigured(self, tmp_path: Path) -> None:
        assert build_mailer(load_settings(env_dir=tmp_path)) is None

    def test_builds_mailer_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SILVERFISH_SMTP_USERNAME", "u@example.com")
        mailer = build_mailer(load_settings(env_dir=tmp_path))
        assert isinstance(mailer, SmtpMailer)

    def test_unknown_security_falls_back_to_starttls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SILVERFISH_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SILVERFISH_SMTP_SECURITY", "bogus")
        mailer = build_mailer(load_settings(env_dir=tmp_path))
        assert isinstance(mailer, SmtpMailer)
        # The built settings default to STARTTLS on an unknown value.
        assert mailer._settings.security == SmtpSecurity.STARTTLS
