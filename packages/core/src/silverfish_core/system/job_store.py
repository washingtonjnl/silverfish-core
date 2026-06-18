"""SQL implementation of the ``JobStore`` port over the system database.

Persists each job's observable state in the ``jobs`` table. The work itself is
never persisted — on startup, ``reconcile_interrupted`` moves any job left
queued/running to a terminal error (it could not have finished), which also
frees its dedup key.
"""

from sqlalchemy import select, update

from silverfish_core.jobs.store import ACTIVE_STATUSES, JobState
from silverfish_core.system.db import SystemDatabase
from silverfish_core.system.models import JobRecord

_INTERRUPTED_MESSAGE = "Interrupted by a server restart"


class SqlJobStore:
    """Persist and query job state in the system database."""

    def __init__(self, database: SystemDatabase) -> None:
        self._db = database

    def save(self, state: JobState) -> None:
        with self._db.session() as session:
            row = session.get(JobRecord, state.id)
            if row is None:
                session.add(_to_row(state))
            else:
                row.type = state.type
                row.status = state.status
                row.progress = state.progress
                row.message = state.message
                row.result = state.result
                row.error = state.error
                row.key = state.key
            session.commit()

    def get(self, job_id: str) -> JobState | None:
        with self._db.session() as session:
            row = session.get(JobRecord, job_id)
            return _to_state(row) if row is not None else None

    def find_active(self, key: str) -> JobState | None:
        if not key:
            return None
        with self._db.session() as session:
            stmt = select(JobRecord).where(
                JobRecord.key == key, JobRecord.status.in_(ACTIVE_STATUSES)
            )
            row = session.scalars(stmt).first()
            return _to_state(row) if row is not None else None

    def reconcile_interrupted(self) -> None:
        with self._db.session() as session:
            session.execute(
                update(JobRecord)
                .where(JobRecord.status.in_(ACTIVE_STATUSES))
                .values(status="error", error=_INTERRUPTED_MESSAGE)
            )
            session.commit()


def _to_row(state: JobState) -> JobRecord:
    return JobRecord(
        id=state.id,
        type=state.type,
        status=state.status,
        progress=state.progress,
        message=state.message,
        result=state.result,
        error=state.error,
        key=state.key,
    )


def _to_state(row: JobRecord) -> JobState:
    return JobState(
        id=row.id,
        type=row.type,
        status=row.status,
        progress=row.progress,
        message=row.message,
        result=row.result,
        error=row.error,
        key=row.key,
    )
