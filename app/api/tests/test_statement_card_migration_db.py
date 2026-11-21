"""Revision 0007 against a real Postgres (BE-09): the card columns, their checks,
the downgrade, the grants of app_backend and the drift check. Run by make
test-db; each test uses a throwaway database (test_migrations_db.database)."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from server.db import Base
from test_migrations_db import (  # noqa: F401  (fixtures)
    alembic_config,
    as_role,
    database,
    drift,
    migrated,
    owner,
)
from test_transactions_db import make_user

pytestmark = pytest.mark.db


def insert_statement(connection, user_id, card_name=None, card_last4=None):
    return connection.execute(
        text(
            "insert into portal.statements (user_id, name, card_name, card_last4) "
            "values (:u, 'Fatura Cartão Exemplo, set/2026', :n, :d) returning id"
        ),
        {"u": user_id, "n": card_name, "d": card_last4},
    ).scalar_one()


def test_card_columns_types_and_nullability(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select column_name, data_type, character_maximum_length, is_nullable "
                "from information_schema.columns where table_schema = 'portal' "
                "and table_name = 'statements' and column_name like 'card_%' "
                "order by column_name"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("card_last4", "character", 4, "YES"),
        ("card_name", "text", None, "YES"),
    ]


def test_card_last4_rejects_non_digits(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_card_last4_digits"):
            insert_statement(connection, user_id, card_last4="00A0")


def test_card_last4_rejects_three_digits(migrated):
    # Three digits: the pattern needs exactly four.
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_card_last4_digits"):
            insert_statement(connection, user_id, card_last4="000")


def test_card_last4_rejects_five_digits(migrated):
    # Five characters do not fit char(4): PostgreSQL refuses the value before the check runs.
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(DataError):
            insert_statement(connection, user_id, card_last4="00000")


def test_card_name_rejects_empty(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        with pytest.raises(IntegrityError, match="ck_statements_card_name_not_empty"):
            insert_statement(connection, user_id, card_name="")


def test_null_card_fields_are_allowed(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = insert_statement(connection, user_id)
        row = connection.execute(
            text("select card_name, card_last4 from portal.statements where id = :id"),
            {"id": statement_id},
        ).one()
    assert tuple(row) == (None, None)


def test_downgrade_removes_card_columns(database):
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "0006")

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
                "('ck_statements_card_name_not_empty', 'ck_statements_card_last4_digits')"
            )
        ).scalar_one()
    assert "card_name" not in columns
    assert "card_last4" not in columns
    assert checks == 0

    command.upgrade(config, "head")
    with owner(database).connect() as connection:
        restored = connection.execute(
            text(
                "select count(*) from information_schema.columns "
                "where table_schema = 'portal' and table_name = 'statements' "
                "and column_name like 'card_%'"
            )
        ).scalar_one()
    assert restored == 2


def test_app_role_reads_and_writes_card_columns(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)

    engine = as_role("app_backend", migrated)
    try:
        with engine.begin() as connection:
            statement_id = insert_statement(
                connection, user_id, card_name="Cartão Exemplo", card_last4="0000"
            )
            connection.execute(
                text("update portal.statements set card_last4 = '0123' where id = :id"),
                {"id": statement_id},
            )
            row = connection.execute(
                text("select card_name, card_last4 from portal.statements where id = :id"),
                {"id": statement_id},
            ).one()
    finally:
        engine.dispose()
    assert tuple(row) == ("Cartão Exemplo", "0123")


def test_models_match_migrations(migrated):
    with owner(migrated).connect() as connection:
        assert drift(connection, Base.metadata) == []
