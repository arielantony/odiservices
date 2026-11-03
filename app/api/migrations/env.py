import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from migrations.guards import (
    migration_url,
    next_revision_id,
    refuse_remote_downgrade,
)
from server.db.base import SCHEMA, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Supabase owns other schemas (public, auth, storage, ...): leave them.
    if type_ == "schema":
        return name == SCHEMA
    return True


def next_id(migration_context, revision, directives):
    script = directives[0]
    head = context.script.get_current_head()
    script.rev_id = next_revision_id(head)


def is_downgrade() -> bool:
    command = getattr(config.cmd_opts, "cmd", None)
    return bool(command) and command[0].__name__ == "downgrade"


def configure_options() -> dict:
    return dict(
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
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
    if is_downgrade():
        refuse_remote_downgrade(url)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            # Alembic's version table lives in the schema, so it comes first.
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
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
