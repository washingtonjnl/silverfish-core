"""Book endpoints: upload, list, get and search."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status

from silverfish_api.deps import ImportServiceDep, RepositoryDep, StorageDep
from silverfish_api.errors import ERROR_400, ERROR_404, ERROR_422, ERROR_500
from silverfish_api.schemas import BookOut, BookPage
from silverfish_core.domain.models import Book
from silverfish_core.ports import FileStorage
from silverfish_core.ports.types import (
    Page,
    SearchFilters,
    SortDirection,
    SortField,
    SortOrder,
)
from silverfish_core.services.import_book import UploadedFile

router = APIRouter(tags=["books"])


def _read_or_none(storage: FileStorage, relative_path: str | None) -> bytes | None:
    """Read a file via storage, returning ``None`` if the path is unknown or the
    file is missing. Keeps the not-found handling in one place.
    """
    if relative_path is None:
        return None
    try:
        return storage.read_book_file(relative_path)
    except (FileNotFoundError, ValueError):
        return None


# Formats accepted for upload (mirrors Calibre's common set).
ALLOWED_UPLOAD_EXTENSIONS = (
    "epub",
    "kepub",
    "mobi",
    "azw",
    "azw3",
    "pdf",
    "txt",
    "fb2",
    "cbz",
    "cbr",
    "cbt",
    "cb7",
    "djvu",
)

# Listings/search can fail validation (422) or unexpectedly (500), but never
# 404; a by-id lookup adds 404. Upload adds 400 for a rejected file.
_LIST_ERRORS = {**ERROR_422, **ERROR_500}
_GET_ERRORS = {**ERROR_404, **ERROR_422, **ERROR_500}
_UPLOAD_ERRORS = {**ERROR_400, **ERROR_422, **ERROR_500}

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


@router.post(
    "/books",
    response_model=BookOut,
    status_code=status.HTTP_201_CREATED,
    responses=_UPLOAD_ERRORS,
)
async def upload_book(file: UploadFile, import_service: ImportServiceDep) -> BookOut:
    data = await file.read()
    upload = UploadedFile(filename=file.filename or "upload", data=data)
    try:
        book = import_service.import_book(upload, allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BookOut.from_domain(book)


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


@router.get(
    "/books/{book_id}/cover",
    responses={**ERROR_404, **ERROR_500},
    response_class=Response,
)
def get_book_cover(book_id: int, repository: RepositoryDep, storage: StorageDep) -> Response:
    relative = repository.cover_path(book_id)
    data = _read_or_none(storage, relative)
    if data is None:
        raise HTTPException(status_code=404, detail="Cover not found")
    return Response(content=data, media_type="image/jpeg")


@router.get(
    "/books/{book_id}/formats/{book_format}",
    responses={**ERROR_404, **ERROR_500},
    response_class=Response,
)
def download_book_format(
    book_id: int, book_format: str, repository: RepositoryDep, storage: StorageDep
) -> Response:
    relative = repository.format_path(book_id, book_format)
    data = _read_or_none(storage, relative)
    if data is None or relative is None:
        raise HTTPException(status_code=404, detail="Format not found")
    filename = relative.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
