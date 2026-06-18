"""Book endpoints: upload, list, get and search."""

import dataclasses
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status

from silverfish_api.deps import (
    BookIdDep,
    ConvertServiceDep,
    EditServiceDep,
    ImportServiceDep,
    JobQueueDep,
    PublicIdCodecDep,
    RefreshServiceDep,
    RepositoryDep,
    SendServiceDep,
    StorageDep,
)
from silverfish_api.errors import (
    ERROR_400,
    ERROR_404,
    ERROR_409,
    ERROR_422,
    ERROR_500,
    ERROR_503,
)
from silverfish_api.public_id import PublicIdCodec
from silverfish_api.schemas import (
    BookOut,
    BookPage,
    BookUpdate,
    ConvertRequest,
    JobOut,
    RefreshRequest,
    SendRequest,
)
from silverfish_core.domain.models import Author, Book, Series, Tag
from silverfish_core.jobs.queue import ProgressCallback
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


# Preference order when the client lets the API pick a conversion source — best
# (richest, most reliable) source first. This is API policy, not core logic.
_SOURCE_PRIORITY = ("EPUB", "AZW3", "MOBI", "AZW", "FB2", "PDF", "TXT")


def _resolve_source_format(requested: str | None, available: set[str]) -> str | None:
    """Pick the source format to convert from.

    If the client specified one, use it only when present. Otherwise choose the
    highest-priority format the book actually has.
    """
    if requested is not None:
        return requested.upper() if requested.upper() in available else None
    for candidate in _SOURCE_PRIORITY:
        if candidate in available:
            return candidate
    return next(iter(available), None)


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
# PATCH can 404 (missing book), 400 (empty patch) or 422 (bad field types).
_PATCH_ERRORS = {**ERROR_400, **ERROR_404, **ERROR_422, **ERROR_500}

PageParam = Annotated[int, Query(ge=1)]
PageSizeParam = Annotated[int, Query(ge=1, le=200)]


def _to_page(page: Page[Book], codec: PublicIdCodec) -> BookPage:
    return BookPage(
        items=[BookOut.from_domain(b, codec.encode) for b in page.items],
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
async def upload_book(
    file: UploadFile, import_service: ImportServiceDep, codec: PublicIdCodecDep
) -> BookOut:
    data = await file.read()
    upload = UploadedFile(filename=file.filename or "upload", data=data)
    try:
        book = import_service.import_book(upload, allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BookOut.from_domain(book, codec.encode)


@router.get("/books", response_model=BookPage, responses=_LIST_ERRORS)
def list_books(
    repository: RepositoryDep,
    codec: PublicIdCodecDep,
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
    return _to_page(result, codec)


@router.get("/books/{book_id}", response_model=BookOut, responses=_GET_ERRORS)
def get_book(book_id: BookIdDep, repository: RepositoryDep, codec: PublicIdCodecDep) -> BookOut:
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return BookOut.from_domain(book, codec.encode)


@router.patch("/books/{book_id}", response_model=BookOut, responses=_PATCH_ERRORS)
def update_book(
    book_id: BookIdDep,
    patch: BookUpdate,
    repository: RepositoryDep,
    edit_service: EditServiceDep,
    codec: PublicIdCodecDep,
) -> BookOut:
    if not patch.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided to update",
        )
    current = repository.get_book(book_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Book not found")
    try:
        merged = _apply_update(current, patch)
        updated = edit_service.edit_book(merged)
    except ValueError as exc:
        # A domain rule was violated (e.g. rating out of range) — a bad request,
        # never a 500.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BookOut.from_domain(updated, codec.encode)


@router.delete(
    "/books/{book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROR_404, **ERROR_500},
)
def delete_book(
    book_id: BookIdDep, repository: RepositoryDep, edit_service: EditServiceDep
) -> Response:
    if repository.get_book(book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    edit_service.delete_book(book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _apply_update(book: Book, patch: BookUpdate) -> Book:
    """Merge a partial update onto *book*. Only fields explicitly set on the
    patch are changed (so omitting a field leaves it untouched).
    """
    changes: dict[str, object] = {}
    fields = patch.model_fields_set
    if "title" in fields and patch.title is not None:
        changes["title"] = patch.title
    if "authors" in fields and patch.authors is not None:
        changes["authors"] = tuple(Author(name=n, sort="") for n in patch.authors)
        changes["author_sort"] = ""  # repository recomputes
    if "tags" in fields and patch.tags is not None:
        changes["tags"] = tuple(Tag(name=t) for t in patch.tags)
    if "series" in fields:
        changes["series"] = Series(name=patch.series, sort=patch.series) if patch.series else None
    if "series_index" in fields and patch.series_index is not None:
        changes["series_index"] = patch.series_index
    if "rating" in fields:
        changes["rating"] = patch.rating
    if "languages" in fields and patch.languages is not None:
        changes["languages"] = tuple(patch.languages)
    if "publisher" in fields:
        changes["publisher"] = patch.publisher
    if "comment" in fields:
        changes["comment"] = patch.comment
    return dataclasses.replace(book, **changes)  # type: ignore[arg-type]  # validated field names


@router.get(
    "/books/{book_id}/cover",
    responses={**ERROR_404, **ERROR_500},
    response_class=Response,
)
def get_book_cover(book_id: BookIdDep, repository: RepositoryDep, storage: StorageDep) -> Response:
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
    book_id: BookIdDep, book_format: str, repository: RepositoryDep, storage: StorageDep
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


@router.delete(
    "/books/{book_id}/formats/{book_format}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROR_404, **ERROR_500},
)
def delete_book_format(
    book_id: BookIdDep, book_format: str, repository: RepositoryDep, edit_service: EditServiceDep
) -> Response:
    if repository.get_book(book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if not edit_service.delete_format(book_id, book_format):
        raise HTTPException(status_code=404, detail="Format not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/books/{book_id}/convert",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ERROR_400, **ERROR_404, **ERROR_409, **ERROR_422, **ERROR_503, **ERROR_500},
)
def convert_book(
    book_id: BookIdDep,
    request: ConvertRequest,
    repository: RepositoryDep,
    convert_service: ConvertServiceDep,
    job_queue: JobQueueDep,
) -> JobOut:
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if convert_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversion is unavailable: ebook-convert is not installed",
        )

    target = request.target_format.upper()
    available = {fmt.extension.upper() for fmt in book.formats}
    if target in available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The book already has a {target} format",
        )
    source_format = _resolve_source_format(request.source_format, available)
    if source_format is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No suitable source format is available to convert from",
        )

    # Deduplicate: refuse a second job for the same conversion already in flight.
    dedup_key = f"convert:{book_id}:{source_format}->{target}"
    if job_queue.find_active(dedup_key) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {source_format}->{target} conversion for this book is already in progress",
        )

    service = convert_service

    def work(report: ProgressCallback) -> None:
        service.convert_book(
            book_id=book_id,
            source_format=source_format,
            target_format=target,
            on_progress=report,
        )

    job_id = job_queue.submit("convert", work, key=dedup_key)
    job = job_queue.get(job_id)
    if job is None:  # pragma: no cover - just submitted
        raise HTTPException(status_code=500, detail="Failed to enqueue job")
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
    )


@router.post(
    "/books/{book_id}/refresh-metadata",
    response_model=BookOut,
    responses={**ERROR_400, **ERROR_404, **ERROR_422, **ERROR_500},
)
def refresh_metadata(
    book_id: BookIdDep,
    request: RefreshRequest,
    refresh_service: RefreshServiceDep,
    codec: PublicIdCodecDep,
) -> BookOut:
    try:
        book = refresh_service.refresh(book_id=book_id, source_format=request.source_format)
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message) from exc
    return BookOut.from_domain(book, codec.encode)


@router.post(
    "/books/{book_id}/send",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ERROR_400, **ERROR_404, **ERROR_422, **ERROR_503, **ERROR_500},
)
def send_book(
    book_id: BookIdDep,
    request: SendRequest,
    repository: RepositoryDep,
    send_service: SendServiceDep,
    job_queue: JobQueueDep,
) -> JobOut:
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if send_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sending is unavailable: SMTP is not configured",
        )

    available = {fmt.extension.upper() for fmt in book.formats}
    book_format = _resolve_send_format(request.format, available)
    if book_format is None:
        detail = (
            f"The book has no {request.format.upper()} format"
            if request.format
            else "The book has no sendable format"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    service = send_service
    to_email = request.to_email

    def work(report: ProgressCallback) -> None:
        report(0.1, "Preparing email")
        service.send(book_id=book_id, book_format=book_format, to_email=to_email)
        report(1.0, "Sent")

    job_id = job_queue.submit("send", work, key=f"send:{book_id}:{book_format}:{to_email}")
    job = job_queue.get(job_id)
    if job is None:  # pragma: no cover - just submitted
        raise HTTPException(status_code=500, detail="Failed to enqueue job")
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
    )


def _resolve_send_format(requested: str | None, available: set[str]) -> str | None:
    """Pick the format to send. An explicit request must be present; otherwise
    choose the highest-priority sendable format the book has.
    """
    if requested is not None:
        return requested.upper() if requested.upper() in available else None
    for candidate in _SOURCE_PRIORITY:
        if candidate in available:
            return candidate
    return None


@router.get("/search", response_model=BookPage, responses=_LIST_ERRORS)
def search_books(
    repository: RepositoryDep,
    codec: PublicIdCodecDep,
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
    return _to_page(result, codec)
