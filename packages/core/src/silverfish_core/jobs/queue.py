"""A small thread-backed job queue.

Submitted callables run on a background worker. Each receives a ``report``
callback to publish progress (0.0-1.0). Job state (status, progress, result or
error) is tracked under a lock so it can be polled safely from request threads.
"""

import queue as queue_module
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# A job's work function: it receives a progress-reporting callback and returns
# any result (stored on the job).
ProgressCallback = Callable[[float], None]
JobFunc = Callable[[ProgressCallback], Any]


# Sentinel so _set can distinguish "leave result unchanged" from "set to None".
_UNSET = object()


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    """A unit of background work and its observable state."""

    id: str
    type: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    result: Any = None
    error: str | None = None
    _func: JobFunc | None = field(default=None, repr=False)


class JobQueue:
    """Run jobs on a single background worker thread."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._pending: queue_module.Queue[str] = queue_module.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        # Unblock the worker if it is waiting on the queue.
        self._pending.put("")
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            self._worker = None

    def submit(self, job_type: str, func: JobFunc) -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=job_type, _func=func)
        with self._lock:
            self._jobs[job_id] = job
        self._pending.put(job_id)
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._pending.get()
            if self._stop.is_set() or not job_id:
                continue
            self._execute(job_id)

    def _execute(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None or job._func is None:
            return
        self._set(job_id, status=JobStatus.RUNNING)

        def report(value: float) -> None:
            self._set(job_id, progress=max(0.0, min(1.0, value)))

        try:
            result = job._func(report)
        except Exception as exc:
            # Any failure in user work becomes the job's error state, never
            # crashing the worker thread.
            self._set(job_id, status=JobStatus.ERROR, error=str(exc))
            return
        self._set(job_id, status=JobStatus.DONE, progress=1.0, result=result)

    def _set(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        result: Any = _UNSET,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if result is not _UNSET:
                job.result = result
            if error is not None:
                job.error = error
