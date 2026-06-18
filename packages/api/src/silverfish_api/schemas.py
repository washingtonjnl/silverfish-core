"""Pydantic response schemas — the OpenAPI contract for the API.

Treated as a first-class contract: the quality of these models directly
determines the quality of the generated OpenAPI and therefore the SDKs. They are
plain DTOs mapped from the neutral domain models.
"""

from collections.abc import Callable

from pydantic import BaseModel, Field

from silverfish_core.domain.models import Book


class ErrorDetail(BaseModel):
    """A single field-level validation problem."""

    location: str
    message: str


class ErrorBody(BaseModel):
    """The body of a standardized error."""

    status: int
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    """Every error the API returns shares this shape: ``{"error": {...}}``."""

    error: ErrorBody


class AuthorOut(BaseModel):
    name: str
    sort: str


class SeriesOut(BaseModel):
    name: str
    index: float


class TagOut(BaseModel):
    name: str


class IdentifierOut(BaseModel):
    scheme: str
    value: str


class FormatOut(BaseModel):
    extension: str
    size_bytes: int
    # Ready-to-use URL to download this specific format.
    download_url: str


class BookOut(BaseModel):
    """A book as returned by the API.

    ``id`` is the public form of the book's internal id — always a string so the
    contract keeps one shape, but rendered per library mode (short base62 for
    standalone Snowflake ids, plain decimal for Calibre's small ids).
    """

    id: str
    title: str
    sort: str
    author_sort: str
    authors: list[AuthorOut]
    tags: list[TagOut]
    series: SeriesOut | None
    rating: int | None
    languages: list[str]
    publisher: str | None
    identifiers: list[IdentifierOut]
    formats: list[FormatOut]
    has_cover: bool
    # URL to fetch the cover image, present only when the book has one.
    cover_url: str | None

    @classmethod
    def from_domain(cls, book: Book, encode_id: Callable[[int], str]) -> "BookOut":
        internal_id = book.id if book.id is not None else 0
        book_id = encode_id(internal_id)
        return cls(
            id=book_id,
            title=book.title,
            sort=book.sort,
            author_sort=book.author_sort,
            authors=[AuthorOut(name=a.name, sort=a.sort) for a in book.authors],
            tags=[TagOut(name=t.name) for t in book.tags],
            series=(
                SeriesOut(name=book.series.name, index=book.series_index)
                if book.series is not None
                else None
            ),
            rating=book.rating,
            languages=list(book.languages),
            publisher=book.publisher,
            identifiers=[IdentifierOut(scheme=i.scheme, value=i.value) for i in book.identifiers],
            formats=[
                FormatOut(
                    extension=f.extension,
                    size_bytes=f.size_bytes,
                    download_url=f"/books/{book_id}/formats/{f.extension.lower()}",
                )
                for f in book.formats
            ],
            has_cover=book.has_cover,
            cover_url=f"/books/{book_id}/cover" if book.has_cover else None,
        )


class BookUpdate(BaseModel):
    """A partial book metadata update. Only provided fields are changed.

    ``model_fields_set`` distinguishes "field omitted" from "field set to null",
    so callers can clear a value (e.g. ``rating: null``) deliberately.
    """

    title: str | None = None
    authors: list[str] | None = None
    tags: list[str] | None = None
    series: str | None = None
    series_index: float | None = None
    rating: int | None = Field(default=None, ge=0, le=10)
    languages: list[str] | None = None
    publisher: str | None = None
    comment: str | None = None


class ConvertRequest(BaseModel):
    """Request to convert a book from one format to another."""

    target_format: str
    # Optional: when omitted, the API picks the best available source by a
    # default priority order.
    source_format: str | None = None


class RefreshRequest(BaseModel):
    """Request to refresh a book's metadata from one of its format files."""

    source_format: str


class SendRequest(BaseModel):
    """Request to send a book to an e-reader email address."""

    to_email: str
    # Optional: overrides the default format preference. Must be a format the
    # book actually has, otherwise the request is rejected.
    format: str | None = None


class EmailConfigOut(BaseModel):
    """Non-secret view of the email configuration (never includes the password).

    Whether sending is *available* is reported by ``/health`` (``send_available``);
    this is the detail view for a settings screen.
    """

    configured: bool
    host: str
    port: int
    from_address: str
    security: str


class EmailTestRequest(BaseModel):
    """Request to send a connectivity test email."""

    to_email: str


class ExportRequest(BaseModel):
    """Request to export the library to a Calibre-format zip.

    The export runs asynchronously; a time-limited download link is emailed to
    ``to_email`` when it is ready (the zip is never attached — a library can be
    far larger than any mail server accepts).
    """

    to_email: str


class JobOut(BaseModel):
    """A background job's observable state."""

    id: str
    type: str
    status: str
    progress: float
    # Human-readable description of the current step (from the underlying tool).
    message: str = ""
    error: str | None = None


class BookPage(BaseModel):
    """A paginated page of books."""

    items: list[BookOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool
