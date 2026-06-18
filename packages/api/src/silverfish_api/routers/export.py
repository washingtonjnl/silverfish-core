"""Calibre export endpoints.

``POST /export/calibre`` starts an async job that snapshots the library to a zip
and emails a time-limited download link — it never holds the connection while a
(potentially large) export runs. ``GET /export/download/{token}`` streams the
zip back, with HTTP Range support (resumable downloads) via ``FileResponse``,
and 404s for an unknown or expired token.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from silverfish_api.deps import (
    ExportServiceDep,
    JobQueueDep,
    MailerDep,
    PublicIdCodecDep,
    StoreDep,
)
from silverfish_api.errors import ERROR_400, ERROR_404, ERROR_422, ERROR_500, ERROR_503
from silverfish_api.public_id import PublicIdCodec
from silverfish_api.schemas import ExportRequest, JobOut
from silverfish_core.jobs.queue import ProgressCallback

router = APIRouter(tags=["export"])


def _decode_book_ids(public_ids: list[str] | None, codec: PublicIdCodec) -> list[int] | None:
    """Decode public book ids to internal ids. ``None``/empty stays ``None``
    (export everything). A malformed id is a 400.
    """
    if not public_ids:
        return None
    decoded: list[int] = []
    for public_id in public_ids:
        try:
            decoded.append(codec.decode(public_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid book id: {public_id!r}",
            ) from exc
    return decoded


@router.post(
    "/export/calibre",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ERROR_400, **ERROR_422, **ERROR_503, **ERROR_500},
)
def start_export(
    request: ExportRequest,
    export_service: ExportServiceDep,
    mailer: MailerDep,
    job_queue: JobQueueDep,
    codec: PublicIdCodecDep,
) -> JobOut:
    """Start an async Calibre export; the download link is emailed when ready.

    Enqueues a background job that snapshots the requested books (or the whole
    library when `book_ids` is omitted) to a zip and emails a time-limited link
    to `to_email`, returning 202 with the new job. Responds 503 when export is
    unavailable (the calibredb binary is missing, SMTP is not configured, or no
    public base URL is set for an absolute link), and 400 for a malformed book id.
    """
    if export_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export is unavailable: the calibredb binary was not found.",
        )
    if mailer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export is unavailable: SMTP is not configured to deliver the link.",
        )
    if not export_service.delivers_absolute_links:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Export is unavailable: set SILVERFISH_PUBLIC_BASE_URL so the "
                "emailed download link is an absolute, clickable URL."
            ),
        )

    # Decode the public book ids (base62 strings) to internal ids. Omitted =>
    # whole library. A malformed id is a bad request.
    book_ids = _decode_book_ids(request.book_ids, codec)

    service = export_service
    active_mailer = mailer
    to_email = request.to_email

    def work(report: ProgressCallback) -> None:
        report(0.1, "Building Calibre library")
        result = service.run_export(book_ids)
        report(0.9, "Sending download link")
        active_mailer.send(
            service.build_ready_email(to_email=to_email, download_url=result.download_url)
        )
        report(1.0, "Done")

    job_id = job_queue.submit("export", work)
    job = job_queue.get(job_id)
    if job is None:  # pragma: no cover - just submitted
        raise HTTPException(status_code=500, detail="Failed to enqueue job")
    return JobOut.from_job(job)


@router.get(
    "/export/download/{token}",
    responses={**ERROR_404, **ERROR_500},
    response_class=FileResponse,
)
def download_export(token: str, store: StoreDep) -> FileResponse:
    """Stream a finished export zip for a valid, unexpired token.

    Served via ``FileResponse``, which streams the file and honours HTTP Range
    requests, so a large download is memory-light and resumable.
    """
    path = store.resolve(token)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Export not found or expired")
    return FileResponse(
        path,
        media_type="application/zip",
        filename="silverfish-calibre-export.zip",
    )
