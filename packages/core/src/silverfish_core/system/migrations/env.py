"""Alembic environment for the system database.

Driven programmatically from ``SystemDatabase`` (not the alembic CLI), so the
connection comes in via the config and the target metadata is the system
schema. Runs online (against a live connection) only.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from silverfish_core.system.models import SystemBase

config = context.config
target_metadata = SystemBase.metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite needs batch mode to ALTER TABLE (rebuild) for column changes.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
