import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from migrations.guards import (
    describe_target,
    migration_url,
    next_revision_id,
    refuse_remote_unless_forward,
)
from migrations.options import base_options
from server.db.base import SCHEMA, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def next_id(migration_context, revision, directives):
    script = directives[0]
    head = context.script.get_current_head()
    script.rev_id = next_revision_id(head)


def command_name() -> str | None:
    """The CLI command, or None when Alembic is called from code."""
    command = getattr(config.cmd_opts, "cmd", None)
    return command[0].__name__ if command else None


def configure_options() -> dict:
    return dict(
        target_metadata=target_metadata,
        **base_options(),
        transaction_per_migration=True,
        process_revision_directives=next_id,
    )


def run_migrations_offline() -> None:
    """Print the SQL (the plan the owner reads). Connects to nothing."""
    context.configure(
        dialect_name="postgresql",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **configure_options(),
    )
    with context.begin_transaction():
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        context.run_migrations()


def run_migrations_online() -> None:
    url = migration_url(os.environ)
    refuse_remote_unless_forward(url, command_name())
    print(f"alembic target: {describe_target(url)}", file=sys.stderr)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            # Alembic's version table lives in the schema, so it comes first.
            # Only when it is missing: a read command then needs no CREATE right.
            exists = connection.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = :name"),
                {"name": SCHEMA},
            ).scalar()
            if not exists:
                connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.commit()
            context.configure(connection=connection, **configure_options())
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
