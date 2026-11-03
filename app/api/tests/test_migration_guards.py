import os
import subprocess
import sys
from pathlib import Path

import pytest

from migrations.guards import (
    MigrationGuardError,
    migration_url,
    next_revision_id,
    refuse_remote_downgrade,
)

API = Path(__file__).resolve().parents[1]
REMOTE = "postgresql+psycopg://u:SENHA-FICTICIA@db.example.com/x?sslmode=require"
LOCAL = "postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices"


def alembic(*args, url=None):
    env = {k: v for k, v in os.environ.items() if k != "PORTAL_MIGRATION_DATABASE_URL"}
    if url is not None:
        env["PORTAL_MIGRATION_DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_migration_url_required():
    with pytest.raises(MigrationGuardError, match="PORTAL_MIGRATION_DATABASE_URL"):
        migration_url({})


def test_migration_url_remote_needs_tls():
    url = "postgresql+psycopg://u:SENHA-FICTICIA@db.example.com/x"
    with pytest.raises(MigrationGuardError, match="PORTAL_MIGRATION_DATABASE_URL") as e:
        migration_url({"PORTAL_MIGRATION_DATABASE_URL": url})
    assert "SENHA-FICTICIA" not in str(e.value)
    assert migration_url({"PORTAL_MIGRATION_DATABASE_URL": REMOTE}) == REMOTE


def test_downgrade_refused_on_remote_host():
    with pytest.raises(MigrationGuardError, match="downgrade"):
        refuse_remote_downgrade(REMOTE)
    refuse_remote_downgrade(LOCAL)


def test_downgrade_refused_before_connecting():
    # db.example.com does not answer: a refusal, not a connection error.
    result = alembic("downgrade", "-1", url=REMOTE)
    assert result.returncode != 0
    assert "a downgrade runs only against a database on this machine" in result.stderr
    assert "SENHA-FICTICIA" not in result.stdout + result.stderr


def test_upgrade_without_url_names_the_variable():
    result = alembic("upgrade", "head")
    assert result.returncode != 0
    assert "PORTAL_MIGRATION_DATABASE_URL is not set" in result.stderr


def test_make_db_sql_needs_no_database():
    result = alembic("upgrade", "base:head", "--sql")
    assert result.returncode == 0, result.stderr
    assert "CREATE SCHEMA IF NOT EXISTS portal" in result.stdout


def test_next_revision_id():
    assert next_revision_id(None) == "0001"
    assert next_revision_id("0001") == "0002"
    assert next_revision_id("0009") == "0010"


def test_next_revision_id_rejects_a_non_numeric_head():
    with pytest.raises(MigrationGuardError, match="not a number"):
        next_revision_id("a1b2c3")


def test_every_model_is_in_the_portal_schema():
    from server.db import Base

    assert all(table.schema == "portal" for table in Base.metadata.tables.values())


def test_helper_rejects_a_bad_name():
    from migrations.helpers import enable_backend_only_rls

    with pytest.raises(ValueError):
        enable_backend_only_rls("x; drop table y")
