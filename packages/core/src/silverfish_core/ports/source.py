"""Port: an external book data source (e.g. Z-Library, Anna's Archive).

Each source implements the same contract so the API can expose generic
``/sources/{name}/...`` endpoints. ``download`` returns ``(filename, bytes)``,
which feeds the normal import flow.
"""

from typing import Protocol, runtime_checkable

from silverfish_core.ports.types import ExternalBook, Quota


@runtime_checkable
class DataSource(Protocol):
    """Search and download books from an external provider."""

    name: str

    def search(self, query: str, *, page: int, limit: int) -> tuple[ExternalBook, ...]:
        """Return search hits for *query*."""
        ...

    def get_details(self, external_id: str) -> ExternalBook:
        """Return full details for a single external item."""
        ...

    def download(self, external_id: str) -> tuple[str, bytes]:
        """Download the item, returning ``(filename, file_bytes)``."""
        ...

    def quota(self) -> Quota | None:
        """Return the remaining download allowance, or ``None`` if unlimited."""
        ...
