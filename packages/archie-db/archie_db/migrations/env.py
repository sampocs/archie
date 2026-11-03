"""Alembic environment: runs migrations online against the URL `archie_db.migrate` passes in."""

from alembic import context
from archie_db import models, session


def run_migrations_online() -> None:
    """Apply pending migrations in one transaction."""
    database_url = context.config.get_main_option("sqlalchemy.url")
    if database_url is None:
        raise RuntimeError("sqlalchemy.url is unset; run migrations through archie_db.migrate")

    engine = session.engine_for(database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=models.Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
