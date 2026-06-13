"""Application factory for the Silverfish API.

Kept deliberately thin: it wires the FastAPI app, builds the configured adapters
on startup and includes the routers. Domain behaviour lives in
``silverfish_core``; this layer only translates HTTP to/from it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from silverfish_api import __version__
from silverfish_api.config import load_settings
from silverfish_api.routers import books
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository


class HealthResponse(BaseModel):
    """Liveness payload. Typed so it appears in the OpenAPI contract."""

    status: str
    version: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build adapters on startup and dispose them on shutdown."""
    settings = load_settings()
    repository = SqliteCalibreRepository(db_path=settings.metadata_db)
    app.state.repository = repository
    try:
        yield
    finally:
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

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    app.include_router(books.router)

    return app
