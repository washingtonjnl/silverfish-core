"""SQLAlchemy models for the system database.

The system database is Silverfish's own store, always separate from the book
library. It holds persistent configuration (key/value) and persisted job state.
``SystemBase`` is a distinct ``DeclarativeBase`` — separate from the Calibre and
native book schemas — so ``create_all`` here can never materialise system tables
inside a book library.
"""

from sqlalchemy import Float, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SystemBase(DeclarativeBase):
    pass


class Config(SystemBase):
    """A single persisted configuration entry (key/value)."""

    __tablename__ = "config"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column()


class JobRecord(SystemBase):
    """Persisted observable state of a background job.

    Mirrors ``jobs.queue.Job`` minus the work function: enough to query a job's
    status/progress/result after a restart, and to reconcile jobs left active
    when the process stopped. ``key`` is indexed for the active-by-key lookup.
    """

    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String, default="")
    result: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    key: Mapped[str] = mapped_column(String, default="", index=True)


class ExportToken(SystemBase):
    """A finished export zip's location and expiry, keyed by an opaque token.

    Persisted so an emitted link survives a restart/deploy (an in-memory map
    would be lost, 404-ing every previously-emailed link) and so expiry can
    delete the file wherever it lives. ``remote`` distinguishes a local disk
    path from a storage key (S3/Drive); when remote, ``location`` is the storage
    key and cleanup deletes it through the storage adapter. ``expires_at`` is an
    absolute epoch second; cleanup deletes rows (and files) past it.
    """

    __tablename__ = "export_tokens"
    token: Mapped[str] = mapped_column(String, primary_key=True)
    location: Mapped[str] = mapped_column(String)
    remote: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
