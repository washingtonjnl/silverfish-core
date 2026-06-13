"""Neutral domain models — the storage-agnostic vocabulary of the library.

These are deliberately free of Calibre quirks: ``rating`` is a plain 0-10
integer (the SQLite-Calibre adapter handles the on-disk x2 representation),
collections are immutable tuples, and there is no notion of file paths or SQL
columns here. Every service and adapter speaks in terms of these types.
"""

from dataclasses import dataclass, field
from datetime import datetime

# Rating scale stored by Calibre and enforced by the DB CHECK constraint.
MIN_RATING = 0
MAX_RATING = 10


@dataclass(frozen=True, slots=True)
class Author:
    """A book author with its display name and Calibre-style sort key."""

    name: str
    sort: str
    link: str = ""


@dataclass(frozen=True, slots=True)
class Series:
    """A named series with its sort key."""

    name: str
    sort: str


@dataclass(frozen=True, slots=True)
class Tag:
    """A free-form tag / category."""

    name: str


@dataclass(frozen=True, slots=True)
class Identifier:
    """An external identifier such as ISBN, ASIN, DOI or Goodreads id."""

    scheme: str
    value: str


@dataclass(frozen=True, slots=True)
class BookFormat:
    """A concrete file format available for a book.

    ``extension`` is the uppercase format token (e.g. ``"EPUB"``). ``name`` is
    the on-disk filename without extension. ``size_bytes`` is the uncompressed
    size.
    """

    extension: str
    size_bytes: int
    name: str


@dataclass(frozen=True, slots=True)
class Book:
    """A book aggregate: its core metadata and related entities.

    ``id`` is ``None`` for a book that has not yet been persisted. ``rating`` is
    on a 0-10 scale (``None`` if unrated). Collections are immutable tuples so
    the aggregate as a whole is hashable and safe to share.
    """

    id: int | None
    title: str
    sort: str
    author_sort: str
    authors: tuple[Author, ...] = ()
    tags: tuple[Tag, ...] = ()
    series: Series | None = None
    series_index: float = 1.0
    rating: int | None = None
    languages: tuple[str, ...] = ()
    publisher: str | None = None
    identifiers: tuple[Identifier, ...] = ()
    formats: tuple[BookFormat, ...] = ()
    comment: str | None = None
    has_cover: bool = False
    uuid: str | None = None
    pubdate: datetime | None = None
    timestamp: datetime | None = None
    last_modified: datetime | None = None
    custom_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Rating is a 0-10 scale (Calibre stores it the same way and the DB has a
        # CHECK constraint). Reject out-of-range values here so no consumer can
        # build a Book that would later blow up at the database layer.
        if self.rating is not None and not (MIN_RATING <= self.rating <= MAX_RATING):
            msg = f"rating must be between {MIN_RATING} and {MAX_RATING}, got {self.rating}"
            raise ValueError(msg)
