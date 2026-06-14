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
# any result (stored on the job). The callback takes the progress fraction and
# an optional human-readable message describing the current step.
ProgressCallback = Callable[[float, str], None]
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
    # Human-readable description of the current step (e.g. the binary's line).
    message: str = ""
    result: Any = None
    error: str | None = None
    # Optional dedup key: at most one active (queued/running) job per key.
    key: str = ""
    # Monotonic revision bumped on every state change; lets waiters detect that
    # something changed without missing an update.
    revision: int = 0
    _func: JobFunc | None = field(default=None, repr=False)


_ACTIVE = {JobStatus.QUEUED, JobStatus.RUNNING}


class JobQueue:
    """Run jobs on a single background worker thread."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._pending: queue_module.Queue[str] = queue_module.Queue()
        # A Condition (with its own lock) guards job state and lets waiters block
        # until a change is notified — no busy polling.
        self._cond = threading.Condition()
        self._lock = self._cond
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

    def submit(self, job_type: str, func: JobFunc, *, key: str = "") -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=job_type, key=key, _func=func)
        with self._lock:
            self._jobs[job_id] = job
        self._pending.put(job_id)
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def find_active(self, key: str) -> Job | None:
        """Return a queued-or-running job with this *key*, or ``None``.

        An empty key never matches, so unkeyed jobs are not deduplicated.
        """
        if not key:
            return None
        with self._lock:
            for job in self._jobs.values():
                if job.key == key and job.status in _ACTIVE:
                    return job
        return None

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

        def report(value: float, message: str = "") -> None:
            self._set(job_id, progress=max(0.0, min(1.0, value)), message=message or None)

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
        message: str | None = None,
        result: Any = _UNSET,
        error: str | None = None,
    ) -> None:
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if message is not None:
                job.message = message
            if result is not _UNSET:
                job.result = result
            if error is not None:
                job.error = error
            job.revision += 1
            # Wake any stream waiting on this job's progress.
            self._cond.notify_all()

    def wait_for_change(self, job_id: str, *, since: int, timeout: float) -> tuple[Job | None, int]:
        """Block until the job's revision exceeds *since*, or *timeout* elapses.

        Returns ``(job, revision)``. The thread sleeps (no CPU) until notified by
        a state change. Designed to be called from a threadpool so it never
        blocks an async event loop.
        """
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                return None, since
            if job.revision > since:
                return job, job.revision
            self._cond.wait(timeout=timeout)
            job = self._jobs.get(job_id)
            if job is None:
                return None, since
            return job, job.revision
