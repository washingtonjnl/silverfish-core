"""Pydantic response schemas — the OpenAPI contract for the API.

Treated as a first-class contract: the quality of these models directly
determines the quality of the generated OpenAPI and therefore the SDKs. They are
plain DTOs mapped from the neutral domain models.
"""

from pydantic import BaseModel

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

    @classmethod
    def from_domain(cls, book: Book) -> "BookOut":
        return cls(
            id=book.id if book.id is not None else 0,
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
                FormatOut(extension=f.extension, size_bytes=f.size_bytes) for f in book.formats
            ],
            has_cover=book.has_cover,
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
