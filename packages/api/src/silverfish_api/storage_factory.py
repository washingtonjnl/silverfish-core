"""Storage factory — the single place that maps a storage type to an adapter.

The reference API calls this once at boot to build a global ``FileStorage``. A
SaaS consumer can reuse the same factory per-request to give a particular user a
different backend (e.g. their own bucket) while everyone else falls back to the
global default. Adding a backend means wiring it here only — the core never
changes.
"""

import logging
from typing import assert_never

from silverfish_api.config import Settings, StorageType
from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.ports import FileStorage

logger = logging.getLogger("silverfish")


def build_storage(settings: Settings) -> FileStorage:
    """Build the configured ``FileStorage`` from *settings*.

    Every ``StorageType`` is handled; ``assert_never`` makes adding a new backend
    a type error here until it is wired, so a gap fails at check time, not run
    time.
    """
    if settings.storage is StorageType.LOCAL:
        return LocalFileStorage(root=settings.resolved_storage_dir)
    if settings.storage is StorageType.S3:
        return _build_s3(settings)
    if settings.storage is StorageType.GDRIVE:
        return _build_gdrive(settings)
    assert_never(settings.storage)


def _build_s3(settings: Settings) -> FileStorage:
    """Build an S3 storage adapter, constructing the boto3 client from settings.

    Credentials/region/endpoint come from config; an explicit access key is
    optional (boto3 falls back to the ambient credential chain — IAM role,
    profile — when unset). ``boto3`` is the optional 's3' extra.
    """
    if not settings.s3_bucket:
        msg = "S3 storage requires SILVERFISH_S3_BUCKET to be set."
        raise ValueError(msg)
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        msg = "S3 storage needs the 's3' extra: pip install silverfish-core[s3]"
        raise RuntimeError(msg) from exc

    from silverfish_core.adapters.storage_s3 import S3Storage

    # Pass None for unset values so boto3 falls back to its defaults / ambient
    # credential chain (IAM role, profile). Named args keep the typed overload.
    has_keys = bool(settings.s3_access_key_id and settings.s3_secret_access_key)
    client = boto3.client(
        "s3",
        region_name=settings.s3_region or None,
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id if has_keys else None,
        aws_secret_access_key=settings.s3_secret_access_key if has_keys else None,
    )
    return S3Storage(bucket=settings.s3_bucket, client=client, prefix=settings.s3_prefix)


def _build_gdrive(settings: Settings) -> FileStorage:
    """Build a Google Drive storage adapter from OAuth config.

    Uses the least-privilege ``drive.file`` scope, so the app only touches
    folders it created. The library root folder is the configured
    ``gdrive_folder_id`` when set; otherwise it is created (by name) under My
    Drive and its id is logged so it can be pinned. The OAuth consent flow that
    produces the refresh token is out of band. ``google-api-python-client``/
    ``google-auth`` are the optional 'gdrive' extra.
    """
    if not (settings.gdrive_client_id and settings.gdrive_client_secret):
        msg = "Google Drive storage requires GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET."
        raise ValueError(msg)
    if not settings.gdrive_refresh_token:
        msg = "Google Drive storage requires SILVERFISH_GDRIVE_REFRESH_TOKEN to be set."
        raise ValueError(msg)
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - only without the extra
        msg = "Google Drive storage needs the 'gdrive' extra: pip install silverfish-core[gdrive]"
        raise RuntimeError(msg) from exc

    from silverfish_core.adapters.gdrive_client import GoogleDriveClient
    from silverfish_core.adapters.storage_gdrive import GDriveStorage

    # google-auth ships no stubs, so Credentials is an untyped call.
    credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=settings.gdrive_refresh_token,
        client_id=settings.gdrive_client_id,
        client_secret=settings.gdrive_client_secret,
        token_uri="https://oauth2.googleapis.com/token",  # noqa: S106 - public OAuth endpoint, not a secret
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    client = GoogleDriveClient(service)
    root_id = _ensure_gdrive_root(client, settings)
    return GDriveStorage(client=client, root_folder_id=root_id)


def _ensure_gdrive_root(client: object, settings: Settings) -> str:
    """Return the library root folder id, creating it under My Drive if needed.

    With the drive.file scope the app cannot use a pre-existing folder it did not
    create, so when no id is configured we create one by name and log its id for
    the operator to pin in ``gdrive_folder_id``.
    """
    from silverfish_core.adapters.gdrive_client import GoogleDriveClient

    assert isinstance(client, GoogleDriveClient)  # noqa: S101 - internal call site
    if settings.gdrive_folder_id:
        return settings.gdrive_folder_id
    existing = client.find_child(settings.gdrive_folder_name, "root")
    if existing is not None:
        return existing
    folder_id = client.create_folder(settings.gdrive_folder_name, "root")
    logger.warning(
        "Created Google Drive library folder %r (id=%s). Set "
        "SILVERFISH_GDRIVE_FOLDER_ID=%s to reuse it.",
        settings.gdrive_folder_name,
        folder_id,
        folder_id,
    )
    return folder_id
