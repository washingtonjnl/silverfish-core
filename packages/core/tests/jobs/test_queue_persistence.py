"""Tests for the job queue's optional state persistence (TDD).

When a JobStore is injected, the queue mirrors each job's state to it (so the
history survives a restart) and, on start, reconciles any job left active by a
previous run to a terminal error. Without a store the queue is unchanged
(purely in-memory). A fake in-memory store stands in for the SQL one.
"""

import time
from collections.abc import Callable

from silverfish_core.jobs.queue import JobQueue
from silverfish_core.jobs.store import JobState


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def _status_is(store: "_FakeStore", job_id: str, status: str) -> bool:
    state = store.get(job_id)
    return state is not None and state.status == status


class _FakeStore:
    def __init__(self) -> None:
        self.states: dict[str, JobState] = {}
        self.reconciled = False

    def save(self, state: JobState) -> None:
        self.states[state.id] = state

    def get(self, job_id: str) -> JobState | None:
        return self.states.get(job_id)

    def find_active(self, key: str) -> JobState | None:
        if not key:
            return None
        for state in self.states.values():
            if state.key == key and state.status in ("queued", "running"):
                return state
        return None

    def reconcile_interrupted(self) -> None:
        self.reconciled = True
        for job_id, state in self.states.items():
            if state.status in ("queued", "running"):
                self.states[job_id] = JobState(
                    id=state.id,
                    type=state.type,
                    status="error",
                    progress=state.progress,
                    message=state.message,
                    result=state.result,
                    error="Interrupted by a server restart",
                    key=state.key,
                )


class TestPersistsState:
    def test_completed_job_is_saved(self) -> None:
        store = _FakeStore()
        queue = JobQueue(store=store)
        queue.start()
        try:
            job_id = queue.submit("convert", lambda report: report(1.0, "done"))
            _wait_until(lambda: _status_is(store, job_id, "done"))
        finally:
            queue.stop()
        saved = store.get(job_id)
        assert saved is not None
        assert saved.status == "done"

    def test_failed_job_persists_error(self) -> None:
        store = _FakeStore()
        queue = JobQueue(store=store)
        queue.start()

        def boom(report: object) -> None:
            raise RuntimeError("kaboom")

        try:
            job_id = queue.submit("convert", boom)
            _wait_until(lambda: _status_is(store, job_id, "error"))
        finally:
            queue.stop()
        saved = store.get(job_id)
        assert saved is not None
        assert saved.error is not None and "kaboom" in saved.error


class TestReconcileOnStart:
    def test_start_reconciles_interrupted_jobs(self) -> None:
        store = _FakeStore()
        # Simulate a job left 'running' by a previous process.
        store.states["old"] = JobState(
            id="old",
            type="convert",
            status="running",
            progress=0.5,
            message="",
            result=None,
            error=None,
            key="convert:1:EPUB",
        )
        queue = JobQueue(store=store)
        queue.start()
        try:
            assert store.reconciled is True
            assert store.states["old"].status == "error"
        finally:
            queue.stop()


class TestDedupAcrossRestart:
    def test_find_active_consults_the_store(self) -> None:
        # A persisted active job with a key should be found even though the queue
        # has no in-memory record of it (e.g. just after a restart).
        store = _FakeStore()
        store.states["persisted"] = JobState(
            id="persisted",
            type="convert",
            status="running",
            progress=0.0,
            message="",
            result=None,
            error=None,
            key="convert:1:EPUB",
        )
        queue = JobQueue(store=store)
        # Note: not started, so reconcile has not run; find_active still sees it.
        found = queue.find_active("convert:1:EPUB")
        assert found is not None
        assert found.id == "persisted"


class TestWithoutStore:
    def test_queue_works_without_a_store(self) -> None:
        queue = JobQueue()  # no store
        queue.start()
        try:
            job_id = queue.submit("convert", lambda report: report(1.0, "ok"))
            _wait_until(lambda: (j := queue.get(job_id)) is not None and j.status == "done")
        finally:
            queue.stop()
