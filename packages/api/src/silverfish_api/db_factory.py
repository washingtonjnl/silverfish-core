"""Database factories — the single place that maps settings to a repository.

``build_library_repository`` selects the right ``MetadataRepository`` for the
configured library mode: the native repository (our own schema, SQLite or
Postgres) in standalone mode, or the Calibre repository reading an existing
``metadata.db`` in calibre mode. ``build_system_db`` builds Silverfish's own
config store. A SaaS consumer can reuse these to swap backends per tenant; the
core never changes.
"""

import time
from pathlib import Path

from sqlalchemy.engine import make_url

from silverfish_api.config import LibraryMode, Settings
from silverfish_core.adapters.repo_sql_native import SqlNativeRepository
from silverfish_core.adapters.repo_sqlite_calibre import SqliteCalibreRepository
from silverfish_core.ids import SnowflakeGenerator
from silverfish_core.ports import MetadataRepository
from silverfish_core.system import SystemDatabase

# Custom epoch for Snowflake ids: 2024-01-01T00:00:00Z in milliseconds. Fixed
# forever — changing it would renumber future ids relative to past ones.
_SNOWFLAKE_EPOCH_MS = 1_704_067_200_000


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def _sqlite_path(url: str) -> Path:
    database = make_url(url).database
    if database is None:
        msg = f"SQLite URL has no file path: {url}"
        raise ValueError(msg)
    return Path(database)


def build_library_repository(settings: Settings) -> MetadataRepository:
    """Build the configured book-library repository.

    Standalone mode returns the native repository (creating its schema). Calibre
    mode returns the Calibre repository over the existing ``metadata.db``, which
    must already exist — the core never creates a Calibre library.
    """
    url = settings.resolved_library_db

    if settings.library_mode is LibraryMode.CALIBRE:
        if not _is_sqlite(url):
            msg = "Calibre mode requires a SQLite metadata.db, not a remote database."
            raise NotImplementedError(msg)
        db_path = _sqlite_path(url)
        if not db_path.exists():
            msg = (
                f"no Calibre library (metadata.db) was found at {db_path}. "
                "Calibre mode reads an existing library and never creates one. "
                "Point SILVERFISH_LIBRARY_DIR at a folder that contains a "
                "metadata.db, or switch to standalone mode "
                "(SILVERFISH_LIBRARY_MODE=standalone) to have Silverfish create "
                "and manage its own library."
            )
            raise FileNotFoundError(msg)
        return SqliteCalibreRepository(db_path=db_path)

    # Standalone mode: the core owns the database.
    if not _is_sqlite(url):
        msg = (
            "Postgres for the book library is not wired yet; standalone mode "
            "currently supports SQLite only. The system store may use Postgres."
        )
        raise NotImplementedError(msg)
    # A local SQLite file needs its parent directory to exist first.
    _sqlite_path(url).parent.mkdir(parents=True, exist_ok=True)
    generator = SnowflakeGenerator(
        machine_id=settings.machine_id,
        epoch_ms=_SNOWFLAKE_EPOCH_MS,
        clock=_now_ms,
    )
    return SqlNativeRepository(conn_string=url, id_generator=generator)


def _check_driver_available(url: str) -> None:
    """Fail early with an actionable message if the DB driver isn't installed.

    SQLAlchemy only imports the DBAPI driver lazily (on connect/engine create),
    so a Postgres URL without psycopg otherwise surfaces as a raw
    ``ModuleNotFoundError`` deep in a traceback. Name the fix instead.
    """
    backend = make_url(url).get_backend_name()
    if backend == "sqlite":
        return
    try:
        # get_dialect() loads the dialect; import_dbapi() then imports the actual
        # driver module (psycopg/…) — which is the import that can be missing.
        make_url(url).get_dialect().import_dbapi()
    except ModuleNotFoundError as exc:
        hint = (
            " Install the 'postgres' extra: pip install silverfish-core[postgres]."
            if backend in ("postgresql", "postgres")
            else ""
        )
        msg = f"Database driver for '{backend}' is not installed.{hint}"
        raise RuntimeError(msg) from exc


def build_system_db(settings: Settings) -> SystemDatabase:
    """Build the system store and bring its schema up to date (migrations)."""
    url = settings.resolved_system_db
    _check_driver_available(url)
    if _is_sqlite(url):
        # A local SQLite file needs its parent directory to exist first.
        _sqlite_path(url).parent.mkdir(parents=True, exist_ok=True)
    system = SystemDatabase(conn_string=url)
    system.migrate()
    return system
