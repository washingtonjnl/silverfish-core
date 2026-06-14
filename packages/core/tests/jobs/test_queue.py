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
                report(0.5, "half")
                report(1.0, "done")

            job_id = queue.submit("convert", work)
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.DONE)
            assert _require(queue, job_id).progress == 1.0
        finally:
            queue.stop()


class TestDeduplication:
    def test_find_active_returns_queued_or_running_job(self) -> None:
        queue = JobQueue()  # not started: job stays queued
        job_id = queue.submit("convert", lambda _r: None, key="book:1:EPUB->PDF")
        found = queue.find_active("book:1:EPUB->PDF")
        assert found is not None
        assert found.id == job_id

    def test_find_active_none_for_unknown_key(self) -> None:
        queue = JobQueue()
        queue.submit("convert", lambda _r: None, key="book:1:EPUB->PDF")
        assert queue.find_active("book:2:EPUB->MOBI") is None

    def test_find_active_ignores_finished_jobs(self) -> None:
        queue = JobQueue()
        queue.start()
        try:
            job_id = queue.submit("convert", lambda _r: None, key="k")
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.DONE)
            # A completed job is no longer "active", so the key is free again.
            assert queue.find_active("k") is None
        finally:
            queue.stop()

    def test_jobs_without_key_are_not_deduplicated(self) -> None:
        queue = JobQueue()
        queue.submit("convert", lambda _r: None)
        assert queue.find_active("") is None


class TestWaitForChange:
    def test_returns_immediately_when_already_changed(self) -> None:
        queue = JobQueue()
        job_id = queue.submit("convert", lambda _r: None)
        # We pass a stale revision, so a change is already available.
        job, revision = queue.wait_for_change(job_id, since=-1, timeout=1.0)
        assert job is not None
        assert revision >= 0

    def test_blocks_until_progress_changes(self) -> None:
        queue = JobQueue()
        queue.start()
        try:
            go = threading.Event()
            hold = threading.Event()

            def work(report: ProgressCallback) -> None:
                go.wait(2.0)
                report(0.5, "half")
                hold.wait(2.0)  # pause at 0.5 so the test observes it

            job_id = queue.submit("convert", work)
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.RUNNING)
            current_rev = _require(queue, job_id).revision

            go.set()
            job, new_rev = queue.wait_for_change(job_id, since=current_rev, timeout=2.0)
            assert job is not None
            assert new_rev > current_rev
            assert job.progress == 0.5
            hold.set()
        finally:
            queue.stop()

    def test_times_out_when_no_change(self) -> None:
        queue = JobQueue()
        queue.start()
        try:
            release = threading.Event()
            job_id = queue.submit("convert", lambda _r: release.wait(2.0))
            _wait_until(lambda: _require(queue, job_id).status is JobStatus.RUNNING)
            current_rev = _require(queue, job_id).revision

            # No further change within the timeout -> same revision returned.
            _job, rev2 = queue.wait_for_change(job_id, since=current_rev, timeout=0.2)
            assert rev2 == current_rev
            release.set()
        finally:
            queue.stop()

    def test_unknown_job_returns_none(self) -> None:
        queue = JobQueue()
        job, _ = queue.wait_for_change("nope", since=-1, timeout=0.2)
        assert job is None


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
