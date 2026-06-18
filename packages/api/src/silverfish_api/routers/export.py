"""Calibre export endpoints.

``POST /export/calibre`` starts an async job that snapshots the library to a zip
and emails a time-limited download link — it never holds the connection while a
(potentially large) export runs. ``GET /export/download/{token}`` streams the
zip back, with HTTP Range support (resumable downloads) via ``FileResponse``,
and 404s for an unknown or expired token.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from silverfish_api.deps import ExportServiceDep, JobQueueDep, MailerDep, StoreDep
from silverfish_api.errors import ERROR_404, ERROR_422, ERROR_500, ERROR_503
from silverfish_api.schemas import ExportRequest, JobOut
from silverfish_core.jobs.queue import ProgressCallback

router = APIRouter(tags=["export"])


@router.post(
    "/export/calibre",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**ERROR_422, **ERROR_503, **ERROR_500},
)
def start_export(
    request: ExportRequest,
    export_service: ExportServiceDep,
    mailer: MailerDep,
    job_queue: JobQueueDep,
) -> JobOut:
    """Start an async Calibre export; the download link is emailed when ready."""
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

    service = export_service
    active_mailer = mailer
    to_email = request.to_email

    def work(report: ProgressCallback) -> None:
        report(0.1, "Building Calibre library")
        result = service.run_export()
        report(0.9, "Sending download link")
        active_mailer.send(service.build_ready_email(to_email=to_email, token=result.token))
        report(1.0, "Done")

    job_id = job_queue.submit("export", work)
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
