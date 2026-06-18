"""Storage factory — the single place that maps a storage type to an adapter.

The reference API calls this once at boot to build a global ``FileStorage``. A
SaaS consumer can reuse the same factory per-request to give a particular user a
different backend (e.g. their own bucket) while everyone else falls back to the
global default. Adding a backend means wiring it here only — the core never
changes.
"""

from silverfish_api.config import Settings, StorageType
from silverfish_core.adapters.storage_local import LocalFileStorage
from silverfish_core.ports import FileStorage


def build_storage(settings: Settings) -> FileStorage:
    """Build the configured ``FileStorage`` from *settings*.

    Raises ``NotImplementedError`` for backends that are declared but not yet
    wired, so a misconfiguration fails loudly instead of silently degrading.
    """
    if settings.storage is StorageType.LOCAL:
        return LocalFileStorage(root=settings.resolved_storage_dir)
    if settings.storage is StorageType.S3:
        return _build_s3(settings)
    msg = (
        f"Storage backend '{settings.storage.value}' is not implemented yet. "
        "Available: 'local', 's3'; gdrive is planned."
    )
    raise NotImplementedError(msg)


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
