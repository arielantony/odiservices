"""The baseline against a real Postgres. Run by make test-db; each test uses a
throwaway database on the local Postgres and drops it."""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, text
from sqlalchemy.exc import DBAPIError

from migrations.helpers import enable_backend_only_rls
from server.db import Base

pytestmark = pytest.mark.db

API = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1:55432"
ADMIN_URL = f"postgresql+psycopg://odiservices@{HOST}/odiservices"


def url(role: str, database: str) -> str:
    return f"postgresql+psycopg://{role}@{HOST}/{database}"


@pytest.fixture
def database(monkeypatch):
    name = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    monkeypatch.setenv("PORTAL_MIGRATION_DATABASE_URL", url("odiservices", name))
    yield name
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def alembic_config() -> Config:
    config = Config(str(API / "alembic.ini"))
    config.set_main_option("script_location", str(API / "migrations"))
    return config


@pytest.fixture
def migrated(database):
    command.upgrade(alembic_config(), "head")
    return database


def as_role(role: str, database: str):
    return create_engine(url(role, database))


def owner(database: str):
    return create_engine(url("odiservices", database))


def rls_violations(connection) -> list[str]:
    """Tables in `portal` without RLS, or whose policies are not exactly the
    one for app_backend. Alembic's own version table is not a data table."""
    rows = connection.execute(
        text(
            """
            SELECT c.relname,
                   c.relrowsecurity,
                   coalesce((
                       SELECT array_agg(p.policyname || '=' || array_to_string(p.roles, ','))
                       FROM pg_policies p
                       WHERE p.schemaname = 'portal' AND p.tablename = c.relname
                   ), '{}')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'portal' AND c.relkind IN ('r', 'p')
              AND c.relname <> 'alembic_version'
            """
        )
    ).all()
    return sorted(
        table
        for table, rls, policies in rows
        if not rls or list(policies) != ["backend_only=app_backend"]
    )


def test_upgrade_downgrade_upgrade(database):
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_baseline_creates_schema_and_role(migrated):
    with owner(migrated).connect() as connection:
        schema = connection.execute(
            text("select count(*) from pg_namespace where nspname = 'portal'")
        ).scalar_one()
        flags = connection.execute(
            text(
                "select rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                "from pg_roles where rolname = 'app_backend'"
            )
        ).one()
    assert schema == 1
    assert tuple(flags) == (True, False, False, False, False)


def test_app_backend_cannot_change_the_schema(migrated):
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("create table portal.x (id int)"))
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("drop schema portal"))


def test_app_backend_cannot_read_version_table(migrated):
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("select * from portal.alembic_version"))


def test_role_settings(migrated):
    with owner(migrated).connect() as connection:
        settings = connection.execute(
            text("select rolconfig from pg_roles where rolname = 'app_backend'")
        ).scalar_one()
    assert "statement_timeout=15s" in settings
    assert "idle_in_transaction_session_timeout=30s" in settings


def test_rls_invariant_holds(migrated):
    with owner(migrated).connect() as connection:
        assert rls_violations(connection) == []


def test_rls_invariant_detects_a_bad_table(migrated):
    with owner(migrated).begin() as connection:
        connection.execute(text("create table portal.zz_no_rls (id int)"))
        connection.execute(text("create table portal.zz_public (id int)"))
        connection.execute(text("alter table portal.zz_public enable row level security"))
        connection.execute(
            text("create policy open on portal.zz_public to public using (true)")
        )
        assert rls_violations(connection) == ["zz_no_rls", "zz_public"]


def test_helper_enables_rls_and_policy(migrated):
    engine = owner(migrated)
    with engine.begin() as connection:
        connection.execute(text("create table portal.zz_scratch (id int)"))
        with Operations.context(MigrationContext.configure(connection)):
            enable_backend_only_rls("zz_scratch")
        assert rls_violations(connection) == []
    with as_role("app_backend", migrated).begin() as connection:
        connection.execute(text("insert into portal.zz_scratch values (1)"))
        count = connection.execute(text("select count(*) from portal.zz_scratch")).scalar_one()
    assert count == 1


def test_helper_rejects_a_bad_name():
    with pytest.raises(ValueError):
        enable_backend_only_rls("x; drop table y")


def drift(connection, metadata: MetaData) -> list:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": lambda name, type_, parents: (
                name == "portal" if type_ == "schema" else True
            ),
            "version_table_schema": "portal",
        },
    )
    return compare_metadata(context, metadata)


def test_models_match_migrations(migrated):
    with owner(migrated).connect() as connection:
        assert drift(connection, Base.metadata) == []


def test_drift_check_detects_a_difference(migrated):
    scratch = MetaData(schema="portal")
    Table("zz_drift", scratch, Column("id", Integer), Column("extra", Integer))
    with owner(migrated).begin() as connection:
        connection.execute(text("create table portal.zz_drift (id int)"))
        assert drift(connection, scratch) != []
