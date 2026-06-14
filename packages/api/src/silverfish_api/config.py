"""API configuration via pydantic-settings.

Values are resolved with this precedence (highest first):

    real environment variable  >  .env.local  >  .env  >  built-in default

The library directory is the one knob that matters for the reference API:
``SILVERFISH_LIBRARY_DIR`` points at a Calibre library folder (containing
``metadata.db``). If nothing sets it, a local default directory is used so the
API runs out of the box. Secrets (added later: SMTP, source tokens) belong in
``.env.local``, which is gitignored.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "SILVERFISH_"
DEFAULT_LIBRARY_DIR = "silverfish-library"


class StorageType(StrEnum):
    """Where book files live. Only ``local`` is wired today; the others are
    declared so the selection mechanism and config are ready for cloud backends.
    """

    LOCAL = "local"
    GDRIVE = "gdrive"
    S3 = "s3"


class Settings(BaseSettings):
    """Resolved API settings."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        # Later files take precedence, so .env.local overrides .env. Real
        # environment variables still win over both (pydantic-settings default).
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    library_dir: Path = Field(default=Path(DEFAULT_LIBRARY_DIR))
    storage: StorageType = Field(default=StorageType.LOCAL)
    # Optional explicit directory of the Calibre binaries (ebook-convert,
    # ebook-meta). When unset, they are autodetected from the OS default
    # locations; if still not found, conversion/binary metadata features degrade.
    calibre_bin_dir: Path | None = Field(default=None)

    # SMTP (send-to-ereader). When smtp_host is empty, sending is unavailable
    # (the endpoint returns 503). Secrets belong in .env.local. These credentials
    # are read once at boot and never travel in a send request.
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="")
    smtp_security: str = Field(default="starttls")
    smtp_max_attachment_mb: int = Field(default=25, ge=1)

    @property
    def metadata_db(self) -> Path:
        return self.library_dir / "metadata.db"

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)


def load_settings(env_dir: Path | None = None) -> Settings:
    """Build settings, optionally reading ``.env``/``.env.local`` from *env_dir*.

    *env_dir* exists mainly for tests; in normal use the files are read from the
    current working directory.
    """
    if env_dir is None:
        return Settings()
    # `_env_file` is a documented pydantic-settings runtime override to point at
    # specific env files, but it is not present in the type stubs — hence the
    # justified ignore. Order matters: .env.local overrides .env.
    return Settings(
        _env_file=(env_dir / ".env", env_dir / ".env.local"),  # type: ignore[call-arg]
    )
