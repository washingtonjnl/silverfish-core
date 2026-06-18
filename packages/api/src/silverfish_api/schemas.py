"""Pydantic response schemas — the OpenAPI contract for the API.

Treated as a first-class contract: the quality of these models directly
determines the quality of the generated OpenAPI and therefore the SDKs. They are
plain DTOs mapped from the neutral domain models.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field

from silverfish_core.domain.models import Book

if TYPE_CHECKING:
    from silverfish_core.jobs.queue import Job


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

    Omitting a field leaves it untouched; sending ``null`` clears it (e.g.
    ``rating: null`` removes the rating). Sort keys and the on-disk path are
    recomputed by the server when title/authors change.
    """

    title: str | None = Field(default=None, description="New title.")
    authors: list[str] | None = Field(
        default=None, description="Full author list (replaces the existing one)."
    )
    tags: list[str] | None = Field(
        default=None, description="Full tag list (replaces the existing one)."
    )
    series: str | None = Field(default=None, description="Series name, or null to clear.")
    series_index: float | None = Field(default=None, description="Position within the series.")
    rating: int | None = Field(
        default=None, ge=0, le=10, description="Rating 0-10 (Calibre scale), or null to clear."
    )
    languages: list[str] | None = Field(
        default=None, description="Language codes (replaces the existing list)."
    )
    publisher: str | None = Field(default=None, description="Publisher name, or null to clear.")
    comment: str | None = Field(
        default=None, description="Description/notes (HTML allowed), or null to clear."
    )


class ConvertRequest(BaseModel):
    """Request to convert a book from one format to another."""

    target_format: str = Field(description="Format to produce, e.g. 'EPUB', 'MOBI', 'AZW3', 'PDF'.")
    source_format: str | None = Field(
        default=None,
        description=(
            "Format to convert from. When omitted, the API picks the best "
            "available source by a default priority order."
        ),
    )


class RefreshRequest(BaseModel):
    """Request to refresh a book's metadata from one of its format files."""

    source_format: str = Field(
        description="Which existing format to re-read metadata (and cover) from, e.g. 'EPUB'."
    )


class SendRequest(BaseModel):
    """Request to send a book to an e-reader email address."""

    to_email: EmailStr = Field(description="Destination e-reader address (e.g. your Kindle email).")
    format: str | None = Field(
        default=None,
        description=(
            "Format to send. When omitted, the best available is chosen. Must be "
            "a format the book actually has, otherwise the request is rejected."
        ),
    )


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

    to_email: EmailStr = Field(description="Address to send the SMTP connectivity test email to.")


class ExportRequest(BaseModel):
    """Request to export the library to a Calibre-format zip.

    The export runs asynchronously; a time-limited download link is emailed to
    ``to_email`` when it is ready (the zip is never attached — a library can be
    far larger than any mail server accepts).

    ``book_ids`` selects which books to export (public id strings). Omit it to
    export the whole library.
    """

    to_email: EmailStr = Field(description="Address that receives the download link when ready.")
    book_ids: list[str] | None = Field(
        default=None,
        description="Public ids of the books to export; omit to export the whole library.",
    )


class JobType(StrEnum):
    """The kind of background work a job performs."""

    CONVERT = "convert"
    SEND = "send"
    EXPORT = "export"


class JobStatusOut(StrEnum):
    """A job's lifecycle state (mirrors the core's JobStatus)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class JobOut(BaseModel):
    """A background job's observable state."""

    id: str = Field(description="Opaque job id; poll it at /jobs/{job_id}.")
    type: JobType = Field(description="What kind of work this job performs.")
    status: JobStatusOut = Field(description="Current lifecycle state.")
    progress: float = Field(description="Completion fraction from 0.0 to 1.0.", ge=0.0, le=1.0)
    message: str = Field(default="", description="Human-readable description of the current step.")
    error: str | None = Field(
        default=None, description="Failure reason when status is 'error', else null."
    )

    @classmethod
    def from_job(cls, job: "Job") -> "JobOut":
        """Map a core ``Job`` to the API DTO, narrowing its enums to the contract."""
        return cls(
            id=job.id,
            type=JobType(job.type),
            status=JobStatusOut(job.status),
            progress=job.progress,
            message=job.message,
            error=job.error,
        )


class BookPage(BaseModel):
    """A paginated page of books."""

    items: list[BookOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool
