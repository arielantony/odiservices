"""Revision 0006 against a real Postgres (BE-13): the backfill, the NOT NULL,
the foreign key, the downgrade and the grants of app_backend. Run by make
test-db; each test uses a throwaway database (test_migrations_db.database)."""

import pytest
from alembic import command
import psycopg.errors
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from test_migrations_db import (  # noqa: F401  (fixtures)
    alembic_config,
    as_role,
    database,
    migrated,
    owner,
)
from test_transactions_db import make_statement, make_user

pytestmark = pytest.mark.db

FK = "fk_transactions_original_category_code_categories"


def insert_at_0005(connection, statement_id, item_number, category_code):
    """A line as revision 0005 stores it: no original_category_code yet."""
    connection.execute(
        text(
            "insert into portal.transactions "
            "(statement_id, item_number, section, printed_date, description, amount, category_code) "
            "values (:s, :i, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, :cat)"
        ),
        {"s": statement_id, "i": item_number, "cat": category_code},
    )


def test_backfill_copies_the_current_category(database):
    config = alembic_config()
    command.upgrade(config, "0005")
    with owner(database).begin() as connection:
        statement_id = make_statement(connection, make_user(connection))
        insert_at_0005(connection, statement_id, 1, "FORNECEDOR")
        insert_at_0005(connection, statement_id, 2, "OUTROS")

    command.upgrade(config, "head")

    with owner(database).connect() as connection:
        rows = connection.execute(
            text(
                "select category_code, original_category_code from portal.transactions "
                "order by item_number"
            )
        ).all()
    assert [tuple(row) for row in rows] == [("FORNECEDOR", "FORNECEDOR"), ("OUTROS", "OUTROS")]


def test_column_is_not_null(migrated):
    with owner(migrated).begin() as connection:
        statement_id = make_statement(connection, make_user(connection))
        with pytest.raises(IntegrityError, match="original_category_code") as error:
            connection.execute(
                text(
                    "insert into portal.transactions "
                    "(statement_id, item_number, section, printed_date, description, amount, category_code) "
                    "values (:s, 1, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, 'OUTROS')"
                ),
                {"s": statement_id},
            )
    assert isinstance(error.value.orig, psycopg.errors.NotNullViolation)


def test_original_must_be_a_known_category(migrated):
    with owner(migrated).begin() as connection:
        statement_id = make_statement(connection, make_user(connection))
        with pytest.raises(IntegrityError, match=FK):
            connection.execute(
                text(
                    "insert into portal.transactions "
                    "(statement_id, item_number, section, printed_date, description, amount, "
                    "category_code, original_category_code) "
                    "values (:s, 1, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, "
                    "'OUTROS', 'NAO EXISTE')"
                ),
                {"s": statement_id},
            )


def test_downgrade_removes_the_column(database):
    config = alembic_config()
    command.upgrade(config, "head")
    with owner(database).begin() as connection:
        statement_id = make_statement(connection, make_user(connection))
        connection.execute(
            text(
                "insert into portal.transactions "
                "(statement_id, item_number, section, printed_date, description, amount, "
                "category_code, original_category_code) "
                "values (:s, 1, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, "
                "'FORNECEDOR', 'OUTROS')"
            ),
            {"s": statement_id},
        )

    command.downgrade(config, "0005")

    with owner(database).connect() as connection:
        columns = connection.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'portal' and table_name = 'transactions'"
            )
        ).scalars().all()
        category = connection.execute(
            text("select category_code from portal.transactions")
        ).scalar_one()
        constraints = connection.execute(
            text("select count(*) from pg_constraint where conname = :name"), {"name": FK}
        ).scalar_one()
    assert "original_category_code" not in columns
    assert category == "FORNECEDOR"
    assert constraints == 0


def test_app_backend_reads_and_updates_the_column(migrated):
    with owner(migrated).begin() as connection:
        statement_id = make_statement(connection, make_user(connection))
        connection.execute(
            text(
                "insert into portal.transactions "
                "(statement_id, item_number, section, printed_date, description, amount, "
                "category_code, original_category_code) "
                "values (:s, 1, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, "
                "'FORNECEDOR', 'FORNECEDOR')"
            ),
            {"s": statement_id},
        )

    engine = as_role("app_backend", migrated)
    try:
        with engine.begin() as connection:
            original = connection.execute(
                text("select original_category_code from portal.transactions")
            ).scalar_one()
            connection.execute(
                text("update portal.transactions set original_category_code = 'OUTROS'")
            )
            updated = connection.execute(
                text("select original_category_code from portal.transactions")
            ).scalar_one()
    finally:
        engine.dispose()
    assert original == "FORNECEDOR"
    assert updated == "OUTROS"
