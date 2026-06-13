"""Pydantic response schemas — the OpenAPI contract for the API.

Treated as a first-class contract: the quality of these models directly
determines the quality of the generated OpenAPI and therefore the SDKs. They are
plain DTOs mapped from the neutral domain models.
"""

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
    """A book as returned by the API."""

    id: int
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
    def from_domain(cls, book: Book) -> "BookOut":
        book_id = book.id if book.id is not None else 0
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


class BookPage(BaseModel):
    """A paginated page of books."""

    items: list[BookOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool
