"""Application factory for the Silverfish API.

Kept deliberately thin: it wires the FastAPI app, builds the configured adapters
on startup and includes the routers. Domain behaviour lives in
``silverfish_core``; this layer only translates HTTP to/from it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel

from silverfish_api import __version__
from silverfish_api.config import load_settings
from silverfish_api.errors import ERROR_500, register_error_handlers
from silverfish_api.routers import books, jobs
from silverfish_api.storage_factory import build_storage
from silverfish_core.adapters.calibre_binaries import CalibreBinaries
from silverfish_core.adapters.convert_calibre import CalibreConverter
from silverfish_core.adapters.extract_composite import CompositeMetadataExtractor
from silverfish_core.adapters.extract_ebook_meta import EbookMetaExtractor
from silverfish_core.adapters.extract_python import PythonMetadataExtractor
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.jobs.queue import JobQueue
from silverfish_core.services.convert_book import ConvertBookService
from silverfish_core.services.edit_book import EditBookService
from silverfish_core.services.import_book import ImportBookService
from silverfish_core.services.refresh_metadata import RefreshMetadataService


class BinaryHealthOut(BaseModel):
    """Availability of the Calibre binaries (optional system dependency)."""

    convert_available: bool
    metadata_available: bool


class HealthResponse(BaseModel):
    """Liveness payload. Typed so it appears in the OpenAPI contract."""

    status: str
    version: str
    binaries: BinaryHealthOut


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build adapters on startup and dispose them on shutdown."""
    settings = load_settings()
    repository = SqliteCalibreRepository(db_path=settings.metadata_db)
    storage = build_storage(settings)
    binaries = CalibreBinaries(bin_dir=settings.calibre_bin_dir)

    # EPUB is extracted natively; other formats use ebook-meta when available.
    ebook_meta_extractor = (
        EbookMetaExtractor(ebook_meta=binaries.ebook_meta)
        if binaries.ebook_meta is not None
        else None
    )
    extractor = CompositeMetadataExtractor(
        native=PythonMetadataExtractor(), ebook_meta=ebook_meta_extractor
    )
    import_service = ImportBookService(extractor=extractor, repository=repository, storage=storage)
    edit_service = EditBookService(repository=repository, storage=storage)
    refresh_service = RefreshMetadataService(
        repository=repository,
        storage=storage,
        extractor=extractor,
        edit_service=edit_service,
    )

    job_queue = JobQueue()
    job_queue.start()
    convert_service = (
        ConvertBookService(
            repository=repository,
            storage=storage,
            converter=CalibreConverter(ebook_convert=binaries.ebook_convert),
        )
        if binaries.ebook_convert is not None
        else None
    )

    app.state.repository = repository
    app.state.storage = storage
    app.state.import_service = import_service
    app.state.edit_service = edit_service
    app.state.refresh_service = refresh_service
    app.state.binaries = binaries
    app.state.job_queue = job_queue
    app.state.convert_service = convert_service
    try:
        yield
    finally:
        job_queue.stop()
        repository.close()


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    A factory (rather than a module-level singleton) keeps tests isolated and
    lets consumers assemble the app with their own configuration later.
    """
    app = FastAPI(
        title="Silverfish API",
        version=__version__,
        summary="Open-source core for an ebook library, exposed over HTTP.",
        lifespan=_lifespan,
    )

    register_error_handlers(app)

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["system"],
        responses=ERROR_500,
    )
    def health(request: Request) -> HealthResponse:
        binaries: CalibreBinaries = request.app.state.binaries
        report = binaries.health()
        return HealthResponse(
            status="ok",
            version=__version__,
            binaries=BinaryHealthOut(
                convert_available=report.convert_available,
                metadata_available=report.metadata_available,
            ),
        )

    app.include_router(books.router)
    app.include_router(jobs.router)

    return app
