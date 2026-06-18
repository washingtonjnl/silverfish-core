"""Tests for the SQL job store (TDD).

The job store persists a job's observable STATE (status/progress/result/error)
in the system database, so a restart keeps the history queryable. It does not
re-run work: a job left mid-flight when the server stopped is reconciled to a
terminal 'error' on the next boot, which also frees its dedup key so a new job
for the same input can be created.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from silverfish_core.jobs.store import JobState
from silverfish_core.system.db import SystemDatabase
from silverfish_core.system.job_store import SqlJobStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqlJobStore]:
    db = SystemDatabase(conn_string=f"sqlite:///{tmp_path / 'system.db'}")
    db.create_schema()
    yield SqlJobStore(db)
    db.close()


def _state(**overrides: object) -> JobState:
    base: dict[str, object] = {
        "id": "job-1",
        "type": "convert",
        "status": "queued",
        "progress": 0.0,
        "message": "",
        "result": None,
        "error": None,
        "key": "",
    }
    return JobState(**{**base, **overrides})  # type: ignore[arg-type]


class TestSaveAndGet:
    def test_get_missing_returns_none(self, store: SqlJobStore) -> None:
        assert store.get("nope") is None

    def test_save_then_get(self, store: SqlJobStore) -> None:
        store.save(_state(id="job-1", type="convert", status="running", progress=0.5))
        got = store.get("job-1")
        assert got is not None
        assert got.type == "convert"
        assert got.status == "running"
        assert got.progress == 0.5

    def test_save_is_upsert(self, store: SqlJobStore) -> None:
        store.save(_state(id="job-1", status="queued"))
        store.save(_state(id="job-1", status="done", progress=1.0, result="ok"))
        got = store.get("job-1")
        assert got is not None
        assert got.status == "done"
        assert got.result == "ok"


class TestFindActive:
    def test_finds_active_by_key(self, store: SqlJobStore) -> None:
        store.save(_state(id="job-1", status="running", key="convert:1:EPUB"))
        found = store.find_active("convert:1:EPUB")
        assert found is not None
        assert found.id == "job-1"

    def test_empty_key_never_matches(self, store: SqlJobStore) -> None:
        store.save(_state(id="job-1", status="running", key=""))
        assert store.find_active("") is None

    def test_done_job_is_not_active(self, store: SqlJobStore) -> None:
        store.save(_state(id="job-1", status="done", key="convert:1:EPUB"))
        assert store.find_active("convert:1:EPUB") is None


class TestReconcile:
    def test_interrupted_jobs_become_error(self, store: SqlJobStore) -> None:
        store.save(_state(id="q", status="queued", key="k1"))
        store.save(_state(id="r", status="running", key="k2"))
        store.save(_state(id="d", status="done"))

        store.reconcile_interrupted()

        q, r, d = store.get("q"), store.get("r"), store.get("d")
        assert q is not None and r is not None and d is not None
        assert q.status == "error"
        assert r.status == "error"
        assert d.status == "done"  # terminal job untouched

    def test_reconcile_frees_the_dedup_key(self, store: SqlJobStore) -> None:
        # A crash left a job 'running'; after reconcile its key is free again.
        store.save(_state(id="r", status="running", key="convert:1:EPUB"))
        store.reconcile_interrupted()
        assert store.find_active("convert:1:EPUB") is None

    def test_reconciled_error_has_a_message(self, store: SqlJobStore) -> None:
        store.save(_state(id="r", status="running"))
        store.reconcile_interrupted()
        got = store.get("r")
        assert got is not None
        assert got.error is not None
        assert "interrupt" in got.error.lower()
