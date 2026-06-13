"""Storage factory — the single place that maps a storage type to an adapter.

The reference API calls this once at boot to build a global ``FileStorage``. A
SaaS consumer can reuse the same factory per-request to give a particular user a
different backend (e.g. their own Google Drive) while everyone else falls back
to the global default. Adding Drive/S3 later means wiring them here only — the
core never changes.
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
        return LocalFileStorage(root=settings.library_dir)
    msg = (
        f"Storage backend '{settings.storage.value}' is not implemented yet. "
        "Only 'local' is available; Drive/S3 are planned."
    )
    raise NotImplementedError(msg)
