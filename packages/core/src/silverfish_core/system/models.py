"""SQLAlchemy models for the system database.

The system database is Silverfish's own store, always separate from the book
library. In this phase it holds only persistent configuration as a simple
key/value table. ``SystemBase`` is a distinct ``DeclarativeBase`` — separate
from the Calibre and native book schemas — so ``create_all`` here can never
materialise system tables inside a book library.
"""

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SystemBase(DeclarativeBase):
    pass


class Config(SystemBase):
    """A single persisted configuration entry (key/value)."""

    __tablename__ = "config"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column()
