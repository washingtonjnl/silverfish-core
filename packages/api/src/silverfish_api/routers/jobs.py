"""Job status endpoint: poll a background job's progress and outcome."""

from fastapi import APIRouter, HTTPException

from silverfish_api.deps import JobQueueDep
from silverfish_api.errors import ERROR_404, ERROR_500
from silverfish_api.schemas import JobOut

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut, responses={**ERROR_404, **ERROR_500})
def get_job(job_id: str, job_queue: JobQueueDep) -> JobOut:
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(
        id=job.id, type=job.type, status=job.status, progress=job.progress, error=job.error
    )
