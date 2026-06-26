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
    SettingsDep,
    StorageDep,
    WriteMetadataServiceDep,
)
from silverfish_api.errors import (
    ERROR_400,
    ERROR_404,
    ERROR_409,
    ERROR_413,
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
    WriteMetadataJob,
    WriteMetadataJobsOut,
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


class ConversionError(Exception):
    """A conversion job's work failed; its message becomes the job's error."""


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
_UPLOAD_ERRORS = {**ERROR_400, **ERROR_413, **ERROR_422, **ERROR_500}

# Read the upload body in chunks so an oversized file is rejected without ever
# being fully materialised in memory.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload fully, or raise 413 once it exceeds *max_bytes*.

    Reads in chunks and stops at the first byte over the ceiling, so a hostile
    multi-gigabyte upload never lands entirely in RAM.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file is too large.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# PATCH can 404 (missing book), 400 (empty patch) or 422 (bad field types).
_PATCH_ERRORS = {**ERROR_400, **ERROR_404, **ERROR_422, **ERROR_500}

PageParam = Annotated[int, Query(ge=1)]
PageSizeParam = Annotated[int, Query(ge=1, le=200)]

# Upper bound on how many values a single search filter list may carry. Real
# queries use a handful; a flood of repeated params is rejected with 422 so it
# can't drive a pathological query.
_MAX_FILTER_VALUES = 100


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
    file: UploadFile,
    import_service: ImportServiceDep,
    codec: PublicIdCodecDep,
    settings: SettingsDep,
) -> BookOut:
    """Upload a book file and create a new book.

    Accepts a multipart `file` whose extension must be one of the allowed
    upload formats; metadata is extracted from the file on import. Returns the
    created book with `201`, `400` if the file is rejected (unsupported
    extension or unreadable content), or `413` if it exceeds the upload size
    limit.
    """
    data = await _read_capped(file, settings.upload_max_mb * 1024 * 1024)
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
    """List books, paginated and sorted.

    Returns a page of books controlled by `page` and `page_size`, ordered by
    `sort` field in the given `direction`. Out-of-range pagination values are
    rejected with `422`.
    """
    result = repository.list_books(
        page=page,
        page_size=page_size,
        sort=SortOrder(field=sort, direction=direction),
    )
    return _to_page(result, codec)


@router.get("/books/{book_id}", response_model=BookOut, responses=_GET_ERRORS)
def get_book(book_id: BookIdDep, repository: RepositoryDep, codec: PublicIdCodecDep) -> BookOut:
    """Get a single book by its public id.

    Looks up the book identified by `book_id` (the book's public id) and returns
    its full metadata. Responds with `404` when no such book exists.
    """
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
    """Partially update a book's metadata.

    Applies only the fields explicitly set in the request body, leaving omitted
    fields untouched, and returns the updated book. Responds with `400` when the
    patch is empty or violates a domain rule (e.g. an out-of-range `rating`),
    and `404` when the book does not exist.
    """
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
    """Delete a book and all of its files.

    Removes the book identified by `book_id` along with its stored formats and
    cover, returning `204` with no body on success. Responds with `404` when the
    book does not exist.
    """
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
    """Download a book's cover image.

    Returns the cover bytes as `image/jpeg` for the book identified by
    `book_id`. Responds with `404` when the book has no recorded cover or the
    cover file is missing from storage.
    """
    relative = repository.cover_path(book_id)
    data = _read_or_none(storage, relative)
    if data is None:
        raise HTTPException(status_code=404, detail="Cover not found")
    return Response(content=data, media_type="image/jpeg")


@router.put(
    "/books/{book_id}/cover",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**ERROR_400, **ERROR_404, **ERROR_413, **ERROR_500},
)
async def set_book_cover(
    book_id: BookIdDep,
    file: UploadFile,
    edit_service: EditServiceDep,
    settings: SettingsDep,
) -> Response:
    """Set (replace) a book's cover image.

    Accepts a multipart `file` that must be an image; the bytes are stored as the
    book's cover and the book is marked as having one. Responds `204` on success,
    `400` if the upload isn't an image, `404` if the book doesn't exist, or `413`
    if it exceeds the upload size limit.
    """
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Cover must be an image")
    data = await _read_capped(file, settings.upload_max_mb * 1024 * 1024)
    if not edit_service.set_cover(book_id, data):
        raise HTTPException(status_code=404, detail="Book not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/books/{book_id}/formats/{book_format}",
    responses={**ERROR_404, **ERROR_500},
    response_class=Response,
)
def download_book_format(
    book_id: BookIdDep, book_format: str, repository: RepositoryDep, storage: StorageDep
) -> Response:
    """Download one format of a book.

    Returns the file for the given `book_format` of the book identified by
    `book_id` as an `application/octet-stream` attachment, with the stored
    filename in the `Content-Disposition` header. Responds with `404` when the
    book lacks that format or the file is missing from storage.
    """
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
    """Delete one format of a book.

    Removes the file for the given `book_format` of the book identified by
    `book_id`, returning `204` with no body on success. Responds with `404` when
    the book does not exist or it has no such format.
    """
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
    """Convert a book to another format.

    Enqueues a background conversion to `target_format`, optionally from an
    explicit `source_format` (otherwise the best available source is chosen), and
    returns `202` with a job to poll at `/jobs/{id}`. Responds with `404` if the
    book is missing, `503` if `ebook-convert` is unavailable, `409` if the target
    format already exists or an identical conversion is already in progress, and
    `400` if no suitable source format is available.
    """
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
        result = service.convert_book(
            book_id=book_id,
            source_format=source_format,
            target_format=target,
            on_progress=report,
        )
        # A failed conversion returns ok=False rather than raising; surface it as
        # the job's error so the job ends in 'error' (not a false 'done'), and the
        # new format is never registered.
        if not result.ok:
            raise ConversionError(result.error or "Conversion failed")

    job_id = job_queue.submit("convert", work, key=dedup_key)
    job = job_queue.get(job_id)
    if job is None:  # pragma: no cover - just submitted
        raise HTTPException(status_code=500, detail="Failed to enqueue job")
    return JobOut.from_job(job)


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
    """Re-extract metadata from a book file and return the updated book.

    Reads metadata afresh from the book's `source_format` file and merges it in:
    fields the extraction produced replace the current ones, fields it could not
    read are kept. Responds with `404` when the book or requested format is not
    found, and `400` for any other refresh failure.
    """
    try:
        book = refresh_service.refresh(book_id=book_id, source_format=request.source_format)
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message) from exc
    return BookOut.from_domain(book, codec.encode)


@router.post(
    "/books/{book_id}/write-metadata",
    response_model=WriteMetadataJobsOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ERROR_400, **ERROR_404, **ERROR_409, **ERROR_503, **ERROR_500},
)
def write_metadata(
    book_id: BookIdDep,
    repository: RepositoryDep,
    write_service: WriteMetadataServiceDep,
    job_queue: JobQueueDep,
) -> WriteMetadataJobsOut:
    """Embed the book's current metadata into its files, one job per format.

    Writes the library's metadata back into every format the book has on disk, so
    an e-reader shows what the library shows. Spawns one background job per
    format (returned in `jobs`, each pollable at `/jobs/{id}`), so a slow or
    failing file never blocks the others. Responds with `404` if the book is
    missing, `503` if `ebook-meta` is unavailable, and `400` if the book has no
    files to write into. A format whose write is already in progress is skipped
    rather than duplicated.
    """
    book = repository.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    if write_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Writing metadata is unavailable: ebook-meta is not installed",
        )

    formats = [fmt.extension.upper() for fmt in book.formats]
    if not formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The book has no files to write metadata into",
        )

    service = write_service
    spawned: list[WriteMetadataJob] = []
    for book_format in formats:
        dedup_key = f"write_metadata:{book_id}:{book_format}"
        existing = job_queue.find_active(dedup_key)
        if existing is not None:
            # An identical write is already in flight; reuse it instead of
            # duplicating the work on the same file.
            spawned.append(WriteMetadataJob(format=book_format, job=JobOut.from_job(existing)))
            continue

        def work(report: ProgressCallback, fmt: str = book_format) -> None:
            service.write_format(book_id=book_id, book_format=fmt, on_progress=report)

        job_id = job_queue.submit("write_metadata", work, key=dedup_key)
        job = job_queue.get(job_id)
        if job is None:  # pragma: no cover - just submitted
            raise HTTPException(status_code=500, detail="Failed to enqueue job")
        spawned.append(WriteMetadataJob(format=book_format, job=JobOut.from_job(job)))

    return WriteMetadataJobsOut(jobs=spawned)


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
    """Email a book to a recipient.

    Enqueues a background job to send the book to `to_email` in the requested
    `format` (or the best available sendable format if unspecified), and returns
    `202` with a job to poll at `/jobs/{id}`. Responds with `404` if the book is
    missing, `503` if SMTP is not configured, and `400` if the book has no
    matching or sendable format.
    """
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
    return JobOut.from_job(job)


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
    include_tags: Annotated[list[str] | None, Query(max_length=_MAX_FILTER_VALUES)] = None,
    exclude_tags: Annotated[list[str] | None, Query(max_length=_MAX_FILTER_VALUES)] = None,
    languages: Annotated[list[str] | None, Query(max_length=_MAX_FILTER_VALUES)] = None,
    formats: Annotated[list[str] | None, Query(max_length=_MAX_FILTER_VALUES)] = None,
    rating_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    rating_max: Annotated[int | None, Query(ge=0, le=10)] = None,
) -> BookPage:
    """Search books by a text query and filters.

    Returns a paginated page of books whose title, author, series or tags match
    the query `q` (case-insensitive substring match), narrowed by the optional
    `include_tags`, `exclude_tags`, `languages`, `formats`, and
    `rating_min`/`rating_max` filters. Out-of-range pagination or rating values
    are rejected with `422`.
    """
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
