"""Application factory for the Silverfish API.

Kept deliberately thin: it wires the FastAPI app, builds the configured adapters
on startup and includes the routers. Domain behaviour lives in
``silverfish_core``; this layer only translates HTTP to/from it.
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel

from silverfish_api import __version__
from silverfish_api.config import load_settings
from silverfish_api.db_factory import build_library_repository, build_system_db
from silverfish_api.errors import ERROR_500, register_error_handlers
from silverfish_api.export_service import ExportService
from silverfish_api.export_store import ExportStore
from silverfish_api.mailer_factory import build_mailer
from silverfish_api.purge_scheduler import PurgeScheduler
from silverfish_api.routers import books, config, export, jobs
from silverfish_api.storage_factory import build_storage
from silverfish_core.adapters.calibre_binaries import CalibreBinaries, SubprocessRunner
from silverfish_core.adapters.convert_calibre import CalibreConverter
from silverfish_core.adapters.export_calibre import CalibreExporter
from silverfish_core.adapters.extract_composite import CompositeMetadataExtractor
from silverfish_core.adapters.extract_ebook_meta import EbookMetaExtractor
from silverfish_core.adapters.extract_python import PythonMetadataExtractor
from silverfish_core.jobs.queue import JobQueue
from silverfish_core.services.convert_book import ConvertBookService
from silverfish_core.services.edit_book import EditBookService
from silverfish_core.services.import_book import ImportBookService
from silverfish_core.services.refresh_metadata import RefreshMetadataService
from silverfish_core.services.send_to_ereader import SendToEreaderService
from silverfish_core.system.job_store import SqlJobStore

logger = logging.getLogger("silverfish")

# Errors raised by the boot-time factories that are configuration problems for
# the user to fix, not bugs — these get a clean message instead of a traceback.
_CONFIG_ERRORS = (FileNotFoundError, NotImplementedError)


class StartupError(RuntimeError):
    """A configuration problem detected while starting the app.

    Raised in place of a low-level error so the failure reads as actionable
    guidance (one clear line) rather than a deep framework traceback.
    """


class BinaryHealthOut(BaseModel):
    """Availability of the Calibre binaries (optional system dependency)."""

    convert_available: bool
    metadata_available: bool


class HealthResponse(BaseModel):
    """Liveness payload. Typed so it appears in the OpenAPI contract."""

    status: str
    version: str
    binaries: BinaryHealthOut
    # Whether send-to-ereader is available (SMTP configured).
    send_available: bool


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build adapters on startup and dispose them on shutdown."""
    settings = load_settings()
    try:
        repository = build_library_repository(settings)
        system_db = build_system_db(settings)
        storage = build_storage(settings)
    except _CONFIG_ERRORS as exc:
        # A configuration problem the user can fix, not a bug. Log one clear,
        # actionable line (no traceback) and abort startup. StartupError is a
        # plain RuntimeError subtype embedders/tests can catch; the logged
        # message — not the traceback — is what the operator should read.
        logger.error("Cannot start Silverfish — %s", exc)
        raise StartupError(str(exc)) from None
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

    # Persist job state to the system database so history survives a restart and
    # jobs left active by a crash are reconciled on start.
    job_queue = JobQueue(store=SqlJobStore(system_db))
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

    mailer = build_mailer(settings)
    send_service = (
        SendToEreaderService(
            repository=repository,
            storage=storage,
            mailer=mailer,
            max_attachment_bytes=settings.smtp_max_attachment_mb * 1024 * 1024,
        )
        if mailer is not None
        else None
    )

    # Calibre export: available only when calibredb is present. The store holds
    # finished zips behind time-limited tokens; the service runs the export.
    export_store = ExportStore(
        database=system_db,
        ttl_seconds=settings.export_ttl_minutes * 60,
        clock=time.time,
        storage=storage,
    )
    # Sweep expired export files (local and remote) on a background thread.
    purge_scheduler = PurgeScheduler(
        store=export_store,
        interval_seconds=settings.export_purge_interval_minutes * 60,
    )
    purge_scheduler.start()
    export_service = (
        ExportService(
            exporter=CalibreExporter(
                repository=repository,
                storage=storage,
                calibredb=binaries.calibredb,
                runner=SubprocessRunner(),
            ),
            store=export_store,
            storage=storage,
            work_dir=settings.resolved_export_dir,
            public_base_url=settings.public_base_url,
        )
        if binaries.calibredb is not None
        else None
    )

    app.state.settings = settings
    app.state.repository = repository
    app.state.system_db = system_db
    app.state.storage = storage
    app.state.import_service = import_service
    app.state.edit_service = edit_service
    app.state.refresh_service = refresh_service
    app.state.binaries = binaries
    app.state.job_queue = job_queue
    app.state.convert_service = convert_service
    app.state.mailer = mailer
    app.state.send_service = send_service
    app.state.export_store = export_store
    app.state.export_service = export_service
    app.state.purge_scheduler = purge_scheduler
    try:
        yield
    finally:
        purge_scheduler.stop()
        job_queue.stop()
        repository.close()
        system_db.close()


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
            send_available=request.app.state.mailer is not None,
        )

    app.include_router(books.router)
    app.include_router(jobs.router)
    app.include_router(config.router)
    app.include_router(export.router)

    return app
