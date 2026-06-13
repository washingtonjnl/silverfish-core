"""Read-side book endpoints: list, get and search."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from silverfish_api.deps import RepositoryDep
from silverfish_api.errors import ERROR_404, ERROR_422, ERROR_500
from silverfish_api.schemas import BookOut, BookPage
from silverfish_core.domain.models import Book
from silverfish_core.ports.types import (
    Page,
    SearchFilters,
    SortDirection,
    SortField,
    SortOrder,
)

router = APIRouter(tags=["books"])

# Listings/search can fail validation (422) or unexpectedly (500), but never
# 404; a by-id lookup adds 404.
_LIST_ERRORS = {**ERROR_422, **ERROR_500}
_GET_ERRORS = {**ERROR_404, **ERROR_422, **ERROR_500}

PageParam = Annotated[int, Query(ge=1)]
PageSizeParam = Annotated[int, Query(ge=1, le=200)]


def _to_page(page: Page[Book]) -> BookPage:
    return BookPage(
        items=[BookOut.from_domain(b) for b in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        total_pages=page.total_pages,
        has_next=page.has_next,
        has_prev=page.has_prev,
    )


@router.get("/books", response_model=BookPage, responses=_LIST_ERRORS)
def list_books(
    repository: RepositoryDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    sort: SortField = SortField.TITLE,
    direction: SortDirection = SortDirection.ASC,
) -> BookPage:
    result = repository.list_books(
        page=page,
        page_size=page_size,
        sort=SortOrder(field=sort, direction=direction),
    )
    return _to_page(result)


@router.get("/books/{book_id}", response_model=BookOut, responses=_GET_ERRORS)
def get_book(book_id: int, repository: RepositoryDep) -> BookOut:
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return BookOut.from_domain(book)


@router.get("/search", response_model=BookPage, responses=_LIST_ERRORS)
def search_books(
    repository: RepositoryDep,
    q: str = "",
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    include_tags: Annotated[list[str] | None, Query()] = None,
    exclude_tags: Annotated[list[str] | None, Query()] = None,
    languages: Annotated[list[str] | None, Query()] = None,
    formats: Annotated[list[str] | None, Query()] = None,
    rating_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    rating_max: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> BookPage:
    filters = SearchFilters(
        include_tags=tuple(include_tags or ()),
        exclude_tags=tuple(exclude_tags or ()),
        languages=tuple(languages or ()),
        formats=tuple(formats or ()),
        rating_min=rating_min,
        rating_max=rating_max,
    )
    result = repository.search(q, filters=filters, page=page, page_size=page_size)
    return _to_page(result)
