"""Neutral value objects that form part of the port contracts.

Pagination, search filters, sort options, conversion results, extracted
metadata and external-source results. All frozen and fully typed; no I/O.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import ceil


@dataclass(frozen=True, slots=True)
class Page[T]:
    """A single page of results plus the totals needed to paginate.

    ``page`` is 1-based. ``total`` is the count across all pages. Derived
    properties (``total_pages``/``has_next``/``has_prev``) are computed so
    callers never recompute pagination maths.
    """

    items: tuple[T, ...]
    total: int
    page: int
    page_size: int

    def __post_init__(self) -> None:
        if self.page < 1:
            msg = "page must be >= 1"
            raise ValueError(msg)
        if self.page_size < 1:
            msg = "page_size must be >= 1"
            raise ValueError(msg)

    @property
    def total_pages(self) -> int:
        if self.total <= 0:
            return 1
        return ceil(self.total / self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


class SortField(Enum):
    """Fields a book listing can be sorted by."""

    TITLE = "title"
    AUTHOR = "author"
    PUBDATE = "pubdate"
    TIMESTAMP = "timestamp"
    LAST_MODIFIED = "last_modified"
    SERIES = "series"
    RATING = "rating"


class SortDirection(Enum):
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True)
class SortOrder:
    """A sort instruction for a listing."""

    field: SortField = SortField.TITLE
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Structured filters for advanced search.

    Tags/series/languages/formats support include and exclude sets; rating uses
    an inclusive 0-10 range. A publication-date range is optional. All fields
    default to "no constraint".
    """

    include_tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    include_series: tuple[str, ...] = ()
    exclude_series: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    formats: tuple[str, ...] = ()
    publisher: str | None = None
    rating_min: int | None = None
    rating_max: int | None = None
    pubdate_from: datetime | None = None
    pubdate_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Outcome of an ``ebook-convert`` run."""

    ok: bool
    output_format: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BookMeta:
    """Metadata extracted from an uploaded file (no DB identity yet).

    ``cover`` is the raw image bytes when a cover could be extracted. Mirrors the
    fields Calibre-Web pulls out of EPUB/PDF/etc. during upload.
    """

    title: str
    extension: str
    authors: tuple[str, ...] = ()
    cover: bytes | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    series: str | None = None
    series_index: float | None = None
    languages: tuple[str, ...] = ()
    publisher: str | None = None
    pubdate: datetime | None = None
    identifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ExternalBook:
    """A search hit from an external data source (e.g. Z-Library)."""

    source: str
    external_id: str
    title: str
    authors: tuple[str, ...] = ()
    extension: str | None = None
    languages: tuple[str, ...] = ()
    year: int | None = None
    size_bytes: int | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Quota:
    """Remaining/total allowance for a rate-limited external source."""

    remaining: int
    limit: int
