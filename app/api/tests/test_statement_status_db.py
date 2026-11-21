"""The processing status of a statement against a real Postgres (BE-07): migration
0008, its checks, set_status and the app role. Run by make test-db; each test
uses a throwaway database (test_migrations_db.database)."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.statements import set_status
from test_migrations_db import (  # noqa: F401  (fixtures)
    alembic_config,
    as_role,
    database,
    migrated,
    owner,
)
from test_transactions_db import make_user

pytestmark = pytest.mark.db

INSERT_STATEMENT = text("insert into portal.statements (user_id, name) values (:u, :n) returning id")
INSERT_STATE = text(
    "insert into portal.statements (user_id, name, status, failure_code) "
    "values (:u, :n, :s, :c)"
)
NAME = "Fatura Cartão Exemplo, set/2026"


def test_status_columns(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema = 'portal' and table_name = 'statements' "
                "and column_name in ('status', 'failure_code') order by column_name"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("failure_code", "text", "YES"),
        ("status", "text", "NO"),
    ]


def test_existing_statements_become_ready(database):
    config = alembic_config()
    command.upgrade(config, "0007")
    with owner(database).begin() as connection:
        user_id = make_user(connection)
        connection.execute(
            text("insert into portal.statements (user_id, name) values (:u, :n)"),
            {"u": user_id, "n": NAME},
        )

    command.upgrade(config, "head")

    with owner(database).connect() as connection:
        row = connection.execute(
            text("select status, failure_code from portal.statements")
        ).one()
    assert tuple(row) == ("ready", None)


def test_check_refuses_unknown_status(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_status_known"):
            connection.execute(INSERT_STATE, {"u": user_id, "n": NAME, "s": "archived", "c": None})


def test_check_refuses_failed_without_code(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_failure_consistent"):
            connection.execute(INSERT_STATE, {"u": user_id, "n": NAME, "s": "failed", "c": None})


def test_check_refuses_code_without_failed(migrated):
    # A valid code on a ready statement: only the consistency check can refuse it.
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_failure_consistent"):
            connection.execute(
                INSERT_STATE,
                {"u": user_id, "n": NAME, "s": "ready", "c": "extraction_timeout"},
            )


def test_check_refuses_unknown_failure_code(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_failure_code_known"):
            connection.execute(
                INSERT_STATE,
                {"u": user_id, "n": NAME, "s": "failed", "c": "stack trace"},
            )


def test_set_status_round_trip(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = connection.execute(
            INSERT_STATEMENT, {"u": user_id, "n": NAME}
        ).scalar_one()

    def read(session):
        return tuple(
            session.execute(
                text("select status, failure_code, updated_at from portal.statements where id = :id"),
                {"id": statement_id},
            ).one()
        )

    with Session(owner(migrated)) as session:
        assert set_status(session, statement_id, "processing") is True
        processing = read(session)
        assert processing[:2] == ("processing", None)

        assert set_status(session, statement_id, "failed", "extraction_timeout") is True
        failed = read(session)
        assert failed[:2] == ("failed", "extraction_timeout")
        assert failed[2] > processing[2]

        assert set_status(session, statement_id, "ready") is True
        ready = read(session)
        assert ready[:2] == ("ready", None)
        assert ready[2] > failed[2]


def test_app_role_sets_status(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)

    engine = as_role("app_backend", migrated)
    try:
        with Session(engine) as session:
            statement_id = session.execute(
                INSERT_STATEMENT, {"u": user_id, "n": NAME}
            ).scalar_one()
            session.commit()
            assert set_status(session, statement_id, "failed", "invalid_pdf") is True
            row = session.execute(
                text("select status, failure_code from portal.statements where id = :id"),
                {"id": statement_id},
            ).one()
    finally:
        engine.dispose()
    assert tuple(row) == ("failed", "invalid_pdf")


def test_downgrade_removes_the_columns(database):
    config = alembic_config()
    command.upgrade(config, "head")
    with owner(database).begin() as connection:
        user_id = make_user(connection)
        connection.execute(
            text("insert into portal.statements (user_id, name) values (:u, :n)"),
            {"u": user_id, "n": NAME},
        )

    command.downgrade(config, "0007")
    with owner(database).connect() as connection:
        columns = connection.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'portal' and table_name = 'statements'"
            )
        ).scalars().all()
        checks = connection.execute(
            text(
                "select count(*) from pg_constraint where conname in "
                "('ck_statements_status_known', 'ck_statements_failure_code_known', "
                "'ck_statements_failure_consistent')"
            )
        ).scalar_one()
    assert "status" not in columns
    assert "failure_code" not in columns
    assert checks == 0

    command.upgrade(config, "head")
    with owner(database).connect() as connection:
        row = connection.execute(
            text("select status, failure_code from portal.statements")
        ).one()
    assert tuple(row) == ("ready", None)
