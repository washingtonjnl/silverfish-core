"""The system database: Silverfish's own persistent store.

Always separate from the book library. It persists config, job state and export
tokens. Created and owned by our ORM, so the same code runs on SQLite (local) or
Postgres (robust deployments) — the connection string decides which. Schema is
managed by **Alembic migrations** (applied on ``migrate()``), so it evolves
safely without dropping data when columns/tables change.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from silverfish_core.system.models import Config

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class SystemDatabase:
    """Key/value configuration store backed by SQLite or Postgres."""

    def __init__(self, *, conn_string: str) -> None:
        self._engine = create_engine(conn_string)
        self._conn_string = conn_string

    def migrate(self) -> None:
        """Bring the schema up to date by applying all pending migrations.

        Idempotent: a fresh database is created, an existing one is upgraded in
        place (no data loss), and an up-to-date one is a no-op.
        """
        cfg = AlembicConfig()
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        cfg.set_main_option("sqlalchemy.url", self._conn_string)
        command.upgrade(cfg, "head")

    # Backwards-compatible alias: callers historically called create_schema().
    def create_schema(self) -> None:
        """Deprecated name for :meth:`migrate`."""
        self.migrate()

    def session(self) -> Session:
        """Open a new ORM session on the system engine.

        Lets other system adapters (e.g. the job store) share this database's
        engine without reaching for it directly.
        """
        return Session(self._engine)

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
