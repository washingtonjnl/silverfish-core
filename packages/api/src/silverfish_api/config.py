"""API configuration via pydantic-settings.

Values are resolved with this precedence (highest first):

    real environment variable  >  .env.local  >  .env  >  built-in default

The library layer has two independent databases, each a SQLite path or a
Postgres URL:

* ``SILVERFISH_LIBRARY_DB`` — the book library.
* ``SILVERFISH_SYSTEM_DB``  — Silverfish's own persistent store (config).

``SILVERFISH_LIBRARY_MODE`` selects whether the core owns the library database
(``standalone``: our schema, SQLite or Postgres) or reads an existing Calibre
``metadata.db`` (``calibre``: API-over-an-existing-Calibre).

Storage (where the book files live) is configured separately from the database
via ``SILVERFISH_STORAGE_DIR`` — in a SaaS the files may sit on Drive/S3 with no
relation to where the metadata lives. ``SILVERFISH_LIBRARY_DIR`` remains a
convenience that derives all three local defaults when the explicit knobs are
unset. Secrets (SMTP, tokens) belong in ``.env.local``, which is gitignored.
"""

import re
from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "SILVERFISH_"
DEFAULT_LIBRARY_DIR = "silverfish-library"

# A value is treated as a full SQLAlchemy URL (not a bare filesystem path) when
# it starts with a ``scheme://`` — the scheme may carry a ``+driver`` suffix,
# e.g. ``postgresql+psycopg://`` or ``sqlite:///``.
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


class LibraryMode(StrEnum):
    """Who owns the book library database."""

    # The core creates and owns the database (our schema; SQLite or Postgres).
    STANDALONE = "standalone"
    # The core reads an existing Calibre metadata.db (API over an existing
    # Calibre install). The file must already exist; the core never creates it.
    CALIBRE = "calibre"


class StorageType(StrEnum):
    """Where book files live. Only ``local`` is wired today; the others are
    declared so the selection mechanism and config are ready for cloud backends.
    """

    LOCAL = "local"
    GDRIVE = "gdrive"
    S3 = "s3"


def _as_url(value: str) -> str:
    """Normalise a DB setting into a SQLAlchemy URL.

    A value that already names a scheme (``sqlite:///``, ``postgresql://``…) is
    returned unchanged; a bare filesystem path is treated as a SQLite file.
    """
    if _URL_RE.match(value):
        return value
    return f"sqlite:///{value}"


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
    library_mode: LibraryMode = Field(default=LibraryMode.STANDALONE)

    # Explicit connection strings (SQLite path or Postgres URL). Empty => derive
    # a local default from library_dir.
    library_db: str = Field(default="")
    system_db: str = Field(default="")

    # Where book files live. Empty => default to library_dir. Independent of the
    # database location by design.
    storage: StorageType = Field(default=StorageType.LOCAL)
    storage_dir: str = Field(default="")

    # Per-node id for the Snowflake generator (standalone mode). Distinct values
    # across nodes prevent id collisions; 0 is fine for a single process.
    machine_id: int = Field(default=0, ge=0)

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

    # Calibre export (snapshot a library to a downloadable zip). The zip is
    # ephemeral: a download link is emailed and the file is deleted once this TTL
    # passes. export_dir holds in-progress/finished zips (defaults under the
    # library dir). Export needs SMTP configured to deliver the link.
    export_ttl_hours: int = Field(default=24, ge=1)
    export_dir: str = Field(default="")

    @property
    def resolved_library_db(self) -> str:
        """The book library's connection string (URL).

        Explicit ``library_db`` wins; otherwise a local SQLite default is derived
        from ``library_dir`` — ``metadata.db`` in calibre mode (the file Calibre
        produced), our own ``library.db`` in standalone mode.
        """
        if self.library_db:
            return _as_url(self.library_db)
        filename = "metadata.db" if self.library_mode is LibraryMode.CALIBRE else "library.db"
        return f"sqlite:///{self.library_dir / filename}"

    @property
    def resolved_system_db(self) -> str:
        """The system store's connection string (URL).

        Always a separate database from the library. Explicit ``system_db`` wins;
        otherwise a local ``system.db`` is derived from ``library_dir``.
        """
        if self.system_db:
            return _as_url(self.system_db)
        return f"sqlite:///{self.library_dir / 'system.db'}"

    @property
    def resolved_storage_dir(self) -> Path:
        """Directory for book files. Defaults to ``library_dir`` when unset."""
        return Path(self.storage_dir) if self.storage_dir else self.library_dir

    @property
    def resolved_export_dir(self) -> Path:
        """Directory for export zips. Defaults to ``<library_dir>/exports``."""
        return Path(self.export_dir) if self.export_dir else self.library_dir / "exports"

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
