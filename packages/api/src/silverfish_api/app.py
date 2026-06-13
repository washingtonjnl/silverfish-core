"""Application factory for the Silverfish API.

Kept deliberately thin: it wires the FastAPI app and routers. Domain behaviour
lives in ``silverfish_core``; this layer only translates HTTP to/from it.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from silverfish_api import __version__


class HealthResponse(BaseModel):
    """Liveness payload. Typed so it appears in the OpenAPI contract."""

    status: str
    version: str


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    A factory (rather than a module-level singleton) keeps tests isolated and
    lets consumers assemble the app with their own configuration later.
    """
    app = FastAPI(
        title="Silverfish API",
        version=__version__,
        summary="Open-source core for an ebook library, exposed over HTTP.",
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app
