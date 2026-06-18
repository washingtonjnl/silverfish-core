"""Dependency wiring for the API.

Builds the concrete adapters (here, the SQLite-Calibre repository) from settings
and exposes them to routers via FastAPI's dependency system. Swapping adapters
(e.g. a Postgres repository in the SaaS) happens here, not in the routers.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from silverfish_api.config import Settings
from silverfish_api.export_service import ExportService
from silverfish_api.export_store import ExportStore
from silverfish_api.public_id import PublicIdCodec
from silverfish_core.jobs.queue import JobQueue
from silverfish_core.ports import FileStorage, Mailer, MetadataRepository
from silverfish_core.services.convert_book import ConvertBookService
from silverfish_core.services.edit_book import EditBookService
from silverfish_core.services.import_book import ImportBookService
from silverfish_core.services.refresh_metadata import RefreshMetadataService
from silverfish_core.services.send_to_ereader import SendToEreaderService
from silverfish_core.system import SystemDatabase


def get_settings(request: Request) -> Settings:
    """Return the process-wide resolved settings from the app state."""
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        msg = "Settings are not configured on the application state"
        raise RuntimeError(msg)
    return settings


def get_public_id_codec(request: Request) -> PublicIdCodec:
    """Return a public-id codec configured for the current library mode."""
    return PublicIdCodec(get_settings(request).library_mode)


def decode_book_id(book_id: Annotated[str, Path()], request: Request) -> int:
    """Decode a public book id from the path into the internal integer.

    The encoding depends on the library mode (base62 for standalone, decimal for
    calibre). A malformed id cannot identify any book, so it yields a 404 (not a
    422) — the resource simply does not exist.
    """
    codec = get_public_id_codec(request)
    try:
        return codec.decode(book_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Book not found") from exc


def get_repository(request: Request) -> MetadataRepository:
    """Return the process-wide repository stored on the app state.

    Raises if the app was not wired with a repository (a misconfiguration), so
    routers can rely on a non-null, conforming repository.
    """
    repo = request.app.state.repository
    if not isinstance(repo, MetadataRepository):
        msg = "Repository is not configured on the application state"
        raise RuntimeError(msg)
    return repo


def get_import_service(request: Request) -> ImportBookService:
    """Return the process-wide import service stored on the app state."""
    service = request.app.state.import_service
    if not isinstance(service, ImportBookService):
        msg = "Import service is not configured on the application state"
        raise RuntimeError(msg)
    return service


def get_storage(request: Request) -> FileStorage:
    """Return the process-wide file storage stored on the app state."""
    storage = request.app.state.storage
    if not isinstance(storage, FileStorage):
        msg = "Storage is not configured on the application state"
        raise RuntimeError(msg)
    return storage


def get_edit_service(request: Request) -> EditBookService:
    """Return the process-wide edit service stored on the app state."""
    service = request.app.state.edit_service
    if not isinstance(service, EditBookService):
        msg = "Edit service is not configured on the application state"
        raise RuntimeError(msg)
    return service


def get_job_queue(request: Request) -> JobQueue:
    """Return the process-wide job queue stored on the app state."""
    queue = request.app.state.job_queue
    if not isinstance(queue, JobQueue):
        msg = "Job queue is not configured on the application state"
        raise RuntimeError(msg)
    return queue


def get_convert_service(request: Request) -> ConvertBookService | None:
    """Return the convert service, or ``None`` when ebook-convert is absent."""
    service = request.app.state.convert_service
    if service is not None and not isinstance(service, ConvertBookService):
        msg = "Convert service is misconfigured on the application state"
        raise RuntimeError(msg)
    return service


def get_refresh_service(request: Request) -> RefreshMetadataService:
    """Return the process-wide metadata-refresh service from the app state."""
    service = request.app.state.refresh_service
    if not isinstance(service, RefreshMetadataService):
        msg = "Refresh service is not configured on the application state"
        raise RuntimeError(msg)
    return service


def get_send_service(request: Request) -> SendToEreaderService | None:
    """Return the send-to-ereader service, or ``None`` when SMTP is unconfigured."""
    service = request.app.state.send_service
    if service is not None and not isinstance(service, SendToEreaderService):
        msg = "Send service is misconfigured on the application state"
        raise RuntimeError(msg)
    return service


def get_mailer(request: Request) -> Mailer | None:
    """Return the mailer, or ``None`` when SMTP is unconfigured."""
    mailer = request.app.state.mailer
    if mailer is not None and not isinstance(mailer, Mailer):
        msg = "Mailer is misconfigured on the application state"
        raise RuntimeError(msg)
    return mailer


def get_system_db(request: Request) -> SystemDatabase:
    """Return the process-wide system database from the app state."""
    system_db = request.app.state.system_db
    if not isinstance(system_db, SystemDatabase):
        msg = "System database is not configured on the application state"
        raise RuntimeError(msg)
    return system_db


def get_export_service(request: Request) -> "ExportService | None":
    """Return the export service, or ``None`` when calibredb is absent."""
    service = request.app.state.export_service
    if service is not None and not isinstance(service, ExportService):
        msg = "Export service is misconfigured on the application state"
        raise RuntimeError(msg)
    return service


def get_export_store(request: Request) -> "ExportStore":
    """Return the process-wide export store from the app state."""
    store = request.app.state.export_store
    if not isinstance(store, ExportStore):
        msg = "Export store is not configured on the application state"
        raise RuntimeError(msg)
    return store


SettingsDep = Annotated[Settings, Depends(get_settings)]
RepositoryDep = Annotated[MetadataRepository, Depends(get_repository)]
ImportServiceDep = Annotated[ImportBookService, Depends(get_import_service)]
StorageDep = Annotated[FileStorage, Depends(get_storage)]
EditServiceDep = Annotated[EditBookService, Depends(get_edit_service)]
JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]
ConvertServiceDep = Annotated[ConvertBookService | None, Depends(get_convert_service)]
RefreshServiceDep = Annotated[RefreshMetadataService, Depends(get_refresh_service)]
SendServiceDep = Annotated[SendToEreaderService | None, Depends(get_send_service)]
MailerDep = Annotated[Mailer | None, Depends(get_mailer)]
SystemDbDep = Annotated[SystemDatabase, Depends(get_system_db)]
ExportServiceDep = Annotated[ExportService | None, Depends(get_export_service)]
StoreDep = Annotated[ExportStore, Depends(get_export_store)]

# Decoded internal book id from a public path segment. Routers depend on this
# instead of declaring ``book_id: int`` so the public id stays opaque.
BookIdDep = Annotated[int, Depends(decode_book_id)]
# Public-id codec for the current mode, used to render ids on the way out.
PublicIdCodecDep = Annotated[PublicIdCodec, Depends(get_public_id_codec)]
