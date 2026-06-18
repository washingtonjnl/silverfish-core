"""Port: persistence of job state.

The queue runs work in memory on a worker thread; this port lets it also persist
each job's observable STATE so a restart keeps the history queryable. It never
persists the work itself — a job interrupted by a restart is reconciled to a
terminal error, not resumed. Implemented by an adapter over the system database
(or left unset, in which case the queue stays purely in-memory).
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Active states: a job that has not reached a terminal state. Mirrors the
# queue's notion of active (queued or running) without importing it here.
ACTIVE_STATUSES = ("queued", "running")


@dataclass(frozen=True, slots=True)
class JobState:
    """A snapshot of a job's observable state, for persistence.

    ``result`` is stored as a string (the queue serialises richer results before
    saving). Plain-data mirror of ``jobs.queue.Job`` minus the work function.
    """

    id: str
    type: str
    status: str
    progress: float
    message: str
    result: str | None
    error: str | None
    key: str


@runtime_checkable
class JobStore(Protocol):
    """Persist and query job state."""

    def save(self, state: JobState) -> None:
        """Insert or update the stored state for ``state.id``."""
        ...

    def get(self, job_id: str) -> JobState | None:
        """Return the stored state for *job_id*, or ``None``."""
        ...

    def find_active(self, key: str) -> JobState | None:
        """Return a queued-or-running job with this *key*, or ``None``.

        An empty key never matches (unkeyed jobs are not deduplicated).
        """
        ...

    def reconcile_interrupted(self) -> None:
        """Move every still-active job to a terminal error.

        Called at startup: any job left queued/running when the process stopped
        could not have finished, so it is marked errored — which also frees its
        dedup key so a new job for the same input can be created.
        """
        ...
