"""Tests for the in-process job queue.

Written before the implementation (TDD). The queue runs submitted callables on a
background worker, tracks their status (queued -> running -> done/error) and
exposes progress, so slow work like conversion can be polled instead of blocking
a request.
"""

import threading
import time
from collections.abc import Callable

from silverfish_core.jobs.queue import Job, JobQueue, JobStatus, ProgressCallback


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    msg = "condition not met within timeout"
    raise AssertionError(msg)


def _require(queue: JobQueue, job_id: str) -> Job:
    job = queue.get(job_id)
    assert job is not None
    return job


class TestSubmitAndComplete:
    def test_runs_job_and_marks_done(self) -> None:
        queue = JobQueue()
        queue.start()
        try:
            job_id = queue.submit("convert", lambda _report: "result")
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.DONE)
            job = _require(queue, job_id)
            assert job.status is JobStatus.DONE
            assert job.result == "result"
            assert job.error is None
        finally:
            queue.stop()

    def test_job_starts_queued(self) -> None:
        queue = JobQueue()
        # Not started: the job stays queued.
        job_id = queue.submit("convert", lambda _report: None)
        assert _require(queue, job_id).status is JobStatus.QUEUED

    def test_failing_job_is_marked_error(self) -> None:
        queue = JobQueue()
        queue.start()
        try:

            def boom(_report: ProgressCallback) -> None:
                msg = "kaboom"
                raise RuntimeError(msg)

            job_id = queue.submit("convert", boom)
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.ERROR)
            job = _require(queue, job_id)
            assert job.status is JobStatus.ERROR
            assert job.error is not None
            assert "kaboom" in job.error
        finally:
            queue.stop()


class TestProgress:
    def test_progress_is_reported(self) -> None:
        queue = JobQueue()
        queue.start()
        try:

            def work(report: ProgressCallback) -> None:
                report(0.5)
                report(1.0)

            job_id = queue.submit("convert", work)
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.DONE)
            assert _require(queue, job_id).progress == 1.0
        finally:
            queue.stop()


class TestLifecycle:
    def test_unknown_job_is_none(self) -> None:
        queue = JobQueue()
        assert queue.get("nope") is None

    def test_jobs_run_in_background_not_blocking_submit(self) -> None:
        queue = JobQueue()
        queue.start()
        try:
            release = threading.Event()

            def slow(_report: ProgressCallback) -> str:
                release.wait(2.0)
                return "ok"

            job_id = queue.submit("convert", slow)
            # submit returned immediately while the job is still running.
            assert _require(queue, job_id).status in {JobStatus.QUEUED, JobStatus.RUNNING}
            release.set()
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.DONE)
        finally:
            queue.stop()
