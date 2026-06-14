"""Dependency wiring for the API.

Builds the concrete adapters (here, the SQLite-Calibre repository) from settings
and exposes them to routers via FastAPI's dependency system. Swapping adapters
(e.g. a Postgres repository in the SaaS) happens here, not in the routers.
"""

from typing import Annotated

from fastapi import Depends, Request

from silverfish_core.jobs.queue import JobQueue
from silverfish_core.ports import FileStorage, MetadataRepository
from silverfish_core.services.convert_book import ConvertBookService
from silverfish_core.services.edit_book import EditBookService
from silverfish_core.services.import_book import ImportBookService


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


RepositoryDep = Annotated[MetadataRepository, Depends(get_repository)]
ImportServiceDep = Annotated[ImportBookService, Depends(get_import_service)]
StorageDep = Annotated[FileStorage, Depends(get_storage)]
EditServiceDep = Annotated[EditBookService, Depends(get_edit_service)]
JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]
ConvertServiceDep = Annotated[ConvertBookService | None, Depends(get_convert_service)]
