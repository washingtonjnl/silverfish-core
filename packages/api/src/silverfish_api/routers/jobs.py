"""Job status endpoints: poll a job, or stream its progress via SSE."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from silverfish_api.deps import JobQueueDep
from silverfish_api.errors import ERROR_404, ERROR_500
from silverfish_api.schemas import JobOut
from silverfish_core.jobs.queue import Job, JobStatus

router = APIRouter(tags=["jobs"])

_TERMINAL = {JobStatus.DONE, JobStatus.ERROR}
# Cap on how long a single wait blocks before re-checking; lets the stream
# notice shutdown even if no change arrives. The wait is event-driven, so this
# is a safety ceiling, not a polling interval.
_WAIT_CEILING_SECONDS = 15.0


def _to_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        message=job.message,
        error=job.error,
    )


@router.get("/jobs/{job_id}", response_model=JobOut, responses={**ERROR_404, **ERROR_500})
def get_job(job_id: str, job_queue: JobQueueDep) -> JobOut:
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_out(job)


@router.get(
    "/jobs/{job_id}/stream",
    responses={**ERROR_404, **ERROR_500},
    response_class=StreamingResponse,
)
def stream_job(job_id: str, job_queue: JobQueueDep) -> StreamingResponse:
    """Stream a job's status/progress as Server-Sent Events until it finishes.

    One open connection replaces repeated polling. Updates are event-driven: the
    stream blocks (in a threadpool, so the event loop stays free) until the job
    actually changes, then emits — so it reflects each new binary output, not a
    fixed tick.
    """
    if job_queue.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def events() -> AsyncIterator[str]:
        revision = -1
        while True:
            job, revision = await asyncio.to_thread(
                job_queue.wait_for_change,
                job_id,
                since=revision,
                timeout=_WAIT_CEILING_SECONDS,
            )
            if job is None:
                return
            yield f"data:{json.dumps(_to_out(job).model_dump())}\n\n"
            if job.status in _TERMINAL:
                return

    return StreamingResponse(events(), media_type="text/event-stream")
