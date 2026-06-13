"""Dependency wiring for the API.

Builds the concrete adapters (here, the SQLite-Calibre repository) from settings
and exposes them to routers via FastAPI's dependency system. Swapping adapters
(e.g. a Postgres repository in the SaaS) happens here, not in the routers.
"""

from typing import Annotated

from fastapi import Depends, Request

from silverfish_core.ports import MetadataRepository
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


RepositoryDep = Annotated[MetadataRepository, Depends(get_repository)]
ImportServiceDep = Annotated[ImportBookService, Depends(get_import_service)]
