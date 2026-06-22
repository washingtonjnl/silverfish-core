"""Runtime configuration backed by the system DB's ``config`` table.

A small, explicit key/value layer over ``SystemDatabase`` config: only known
keys may be read or written (an allowlist — the store is not a free-form bag),
and secret keys are write-only (never returned by reads). SMTP settings resolve
as *DB overrides env*: a key present in the store wins; otherwise the value from
the environment-provided settings is used. Editing email is therefore possible
at runtime without touching the deployment's env.
"""

from silverfish_api.config import Settings
from silverfish_api.mailer_factory import build_mailer
from silverfish_core.adapters.mail_smtp import SmtpMailer
from silverfish_core.ports import FileStorage
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.services.send_to_ereader import SendToEreaderService
from silverfish_core.system import SystemDatabase

# Keys the config API may read or write. Anything else is rejected.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        "smtp_security",
        "kindle_email",
    }
)

# Keys whose value is a secret: writable, but never returned by a read.
SECRET_KEYS: frozenset[str] = frozenset({"smtp_password"})


def read_config(system_db: SystemDatabase, keys: list[str]) -> dict[str, str | None]:
    """Return values for the requested allowed keys (None when unset).

    Unknown keys are ignored. Secret keys are never returned as their value;
    instead they read back as a fixed placeholder when set, else None — so a UI
    can show "configured" without learning the secret.
    """
    out: dict[str, str | None] = {}
    for key in keys:
        if key not in ALLOWED_KEYS:
            continue
        stored = system_db.get_config(key)
        if key in SECRET_KEYS:
            out[key] = "********" if stored else None
        else:
            out[key] = stored
    return out


def write_config(system_db: SystemDatabase, values: dict[str, str]) -> list[str]:
    """Persist the given allowed key/values; return the keys actually written.

    Unknown keys raise so the caller can 422. An empty string for a secret key
    is treated as "clear it" (delete), so a UI can blank the password.
    """
    unknown = [k for k in values if k not in ALLOWED_KEYS]
    if unknown:
        msg = f"Unknown config keys: {', '.join(sorted(unknown))}"
        raise ValueError(msg)

    written: list[str] = []
    for key, value in values.items():
        if key in SECRET_KEYS and value == "":
            system_db.delete_config(key)
        else:
            system_db.set_config(key, value)
        written.append(key)
    return written


def resolve_smtp_settings(settings: Settings, system_db: SystemDatabase) -> Settings:
    """Return a copy of ``settings`` with SMTP fields overridden by the store.

    Env provides the defaults; any SMTP key stored in the config DB takes
    precedence. The returned Settings is what the mailer should be built from.
    """
    overrides: dict[str, object] = {}
    mapping = {
        "smtp_host": "smtp_host",
        "smtp_username": "smtp_username",
        "smtp_password": "smtp_password",
        "smtp_from": "smtp_from",
        "smtp_security": "smtp_security",
    }
    for store_key, field in mapping.items():
        value = system_db.get_config(store_key)
        if value is not None:
            overrides[field] = value
    port = system_db.get_config("smtp_port")
    if port is not None and port.isdigit():
        overrides["smtp_port"] = int(port)

    if not overrides:
        return settings
    return settings.model_copy(update=overrides)


def rebuild_mailer(settings: Settings, system_db: SystemDatabase) -> SmtpMailer | None:
    """Build the mailer from the env+store-resolved SMTP settings."""
    return build_mailer(resolve_smtp_settings(settings, system_db))


def build_send_chain(
    settings: Settings,
    system_db: SystemDatabase,
    repository: MetadataRepository,
    storage: FileStorage,
) -> tuple[SmtpMailer | None, SendToEreaderService | None]:
    """Build the mailer and send service from the env+store-resolved SMTP config.

    Used at startup and again whenever SMTP config changes, so a runtime edit
    takes effect without a restart (the send service holds the mailer, so both
    must be rebuilt together).
    """
    resolved = resolve_smtp_settings(settings, system_db)
    mailer = build_mailer(resolved)
    send_service = (
        SendToEreaderService(
            repository=repository,
            storage=storage,
            mailer=mailer,
            max_attachment_bytes=resolved.smtp_max_attachment_mb * 1024 * 1024,
        )
        if mailer is not None
        else None
    )
    return mailer, send_service
