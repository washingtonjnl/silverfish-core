"""The system database: Silverfish's own persistent store.

Always separate from the book library. In this phase it persists only
configuration (jobs remain in memory). It is created and owned by our ORM, so
the same code runs on SQLite (local) or Postgres (robust deployments) — the
connection string decides which. Schema management is a one-shot ``create_all``:
the core's schema is fixed, so versioned migrations (Alembic) are deferred until
a destructive schema change or a production Postgres actually needs them.
"""

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from silverfish_core.system.models import Config, SystemBase


class SystemDatabase:
    """Key/value configuration store backed by SQLite or Postgres."""

    def __init__(self, *, conn_string: str) -> None:
        self._engine = create_engine(conn_string)

    def create_schema(self) -> None:
        """Create the system tables if they do not exist (idempotent)."""
        SystemBase.metadata.create_all(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    def get_config(self, key: str) -> str | None:
        with Session(self._engine) as session:
            row = session.get(Config, key)
            return row.value if row is not None else None

    def set_config(self, key: str, value: str) -> None:
        with Session(self._engine) as session:
            row = session.get(Config, key)
            if row is None:
                session.add(Config(key=key, value=value))
            else:
                row.value = value
            session.commit()

    def delete_config(self, key: str) -> None:
        with Session(self._engine) as session:
            session.execute(delete(Config).where(Config.key == key))
            session.commit()

    def all_config(self) -> dict[str, str]:
        with Session(self._engine) as session:
            return {row.key: row.value for row in session.scalars(select(Config)).all()}
