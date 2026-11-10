"""The transactions table against a real Postgres (BE-29). Run by make test-db; the
fixtures come from the BE-31 tests."""

from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from server.db import Base, Statement, Transaction, User
from test_migrations_db import (  # noqa: F401  (fixtures)
    alembic_config,
    as_role,
    database,
    drift,
    migrated,
    owner,
    rls_violations,
)

pytestmark = pytest.mark.db

SUB = "sub-fulano"
EMAIL = "fulano@exemplo.com"
NAME = "Fatura Cartão Exemplo, set/2026"
CATEGORY = "OUTROS"
INSERT_TRANSACTION = text(
    "insert into portal.transactions "
    "(statement_id, item_number, section, printed_date, description, amount, category_code) "
    "values (:s, :i, :sec, :d, :desc, :amt, :cat)"
)


def make_user(connection) -> str:
    return connection.execute(
        text(
            "insert into portal.users (access_subject, email) values (:s, :e) returning id"
        ),
        {"s": SUB, "e": EMAIL},
    ).scalar_one()


def make_statement(connection, user_id) -> str:
    return connection.execute(
        text("insert into portal.statements (user_id, name) values (:u, :n) returning id"),
        {"u": user_id, "n": NAME},
    ).scalar_one()


def transaction_params(statement_id, **overrides) -> dict:
    params = {
        "s": statement_id,
        "i": 1,
        "sec": "purchases",
        "d": "03/09",
        "desc": "LOJA EXEMPLO 1/3",
        "amt": Decimal("-49.90"),
        "cat": CATEGORY,
    }
    params.update(overrides)
    return params


def test_transactions_columns(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema='portal' and table_name='transactions' order by ordinal_position"
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("id", "uuid", "NO"),
        ("statement_id", "uuid", "NO"),
        ("item_number", "integer", "NO"),
        ("section", "text", "NO"),
        ("printed_date", "text", "NO"),
        ("description", "text", "NO"),
        ("amount", "numeric", "NO"),
        ("category_code", "text", "NO"),
        ("doubtful", "boolean", "NO"),
        ("reviewed", "boolean", "NO"),
        ("created_at", "timestamp with time zone", "NO"),
        ("updated_at", "timestamp with time zone", "NO"),
    ]


def test_defaults_are_set_on_insert(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
        row = connection.execute(
            text(
                "insert into portal.transactions "
                "(statement_id, item_number, section, printed_date, description, amount, category_code) "
                "values (:s, 1, 'purchases', '03/09', 'LOJA EXEMPLO 1/3', -49.90, :cat) "
                "returning substr(id::text, 15, 1) as version, doubtful, reviewed, "
                "created_at, updated_at"
            ),
            {"s": statement_id, "cat": CATEGORY},
        ).one()
    assert row.version == "4"
    assert row.doubtful is False
    assert row.reviewed is False
    assert row.created_at is not None and row.updated_at is not None


def test_updated_at_moves_on_orm_update(migrated):
    with Session(owner(migrated)) as session:
        user = User(access_subject=SUB, email=EMAIL)
        session.add(user)
        session.commit()
        statement = Statement(user_id=user.id, name=NAME)
        session.add(statement)
        session.commit()
        transaction = Transaction(
            statement_id=statement.id,
            item_number=1,
            section="purchases",
            printed_date="03/09",
            description="LOJA EXEMPLO 1/3",
            amount=Decimal("-49.90"),
            category_code=CATEGORY,
        )
        session.add(transaction)
        session.commit()
        updated = transaction.updated_at
        transaction.description = "LOJA EXEMPLO 2/3"
        session.commit()
        session.refresh(transaction)
        assert transaction.updated_at > updated


def test_unknown_category_is_refused(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="fk_transactions_category_code_categories"):
            connection.execute(
                INSERT_TRANSACTION,
                transaction_params(statement_id, cat="CATEGORIA_INEXISTENTE"),
            )


def test_unknown_section_is_refused(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="ck_transactions_section_known"):
            connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, sec="other"))


def test_item_number_must_be_positive(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="ck_transactions_item_number_positive"):
            connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, i=0))


def test_empty_description_and_date_are_refused(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="ck_transactions_description_not_empty"):
            connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, desc=""))
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="ck_transactions_printed_date_not_empty"):
            connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, d=""))


def test_item_number_is_unique_per_statement(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        first = make_statement(connection, user_id)
        second = make_statement(connection, user_id)
        connection.execute(INSERT_TRANSACTION, transaction_params(first, i=1))
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="uq_transactions_statement_id"):
            connection.execute(INSERT_TRANSACTION, transaction_params(first, i=1))
    with owner(migrated).begin() as connection:
        connection.execute(INSERT_TRANSACTION, transaction_params(second, i=1))
        count = connection.execute(
            text("select count(*) from portal.transactions")
        ).scalar_one()
    assert count == 2


def test_amount_keeps_two_decimals_and_allows_negative(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
        connection.execute(
            INSERT_TRANSACTION,
            transaction_params(statement_id, i=1, amt=Decimal("-49.90")),
        )
        connection.execute(
            INSERT_TRANSACTION,
            transaction_params(statement_id, i=2, amt=Decimal("11906.35")),
        )
    with owner(migrated).connect() as connection:
        amounts = connection.execute(
            text("select amount from portal.transactions order by item_number")
        ).scalars().all()
    assert amounts == [Decimal("-49.90"), Decimal("11906.35")]


def test_deleting_a_statement_deletes_its_transactions(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
        connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, i=1))
        connection.execute(INSERT_TRANSACTION, transaction_params(statement_id, i=2))
    with owner(migrated).begin() as connection:
        connection.execute(text("delete from portal.statements"))
    with owner(migrated).connect() as connection:
        count = connection.execute(
            text("select count(*) from portal.transactions")
        ).scalar_one()
    assert count == 0


def test_category_in_use_cannot_be_deleted(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
        connection.execute(INSERT_TRANSACTION, transaction_params(statement_id))
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="fk_transactions_category_code_categories"):
            connection.execute(text("delete from portal.categories where code = :c"), {"c": CATEGORY})


def test_app_role_reads_and_writes_transactions(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        statement_id = make_statement(connection, user_id)
    with as_role("app_backend", migrated).begin() as connection:
        connection.execute(INSERT_TRANSACTION, transaction_params(statement_id))
        count = connection.execute(
            text("select count(*) from portal.transactions")
        ).scalar_one()
        assert count == 1
        connection.execute(
            text("update portal.transactions set reviewed = true")
        )
        connection.execute(text("delete from portal.transactions"))
        count = connection.execute(
            text("select count(*) from portal.transactions")
        ).scalar_one()
        assert count == 0


def test_app_role_cannot_drop_transactions(migrated):
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("drop table portal.transactions"))


def test_downgrade_drops_the_table(migrated):
    config = alembic_config()
    command.downgrade(config, "0004")
    with owner(migrated).connect() as connection:
        exists = connection.execute(
            text("select to_regclass('portal.transactions') is not null")
        ).scalar_one()
    assert exists is False
    command.upgrade(config, "head")
    with owner(migrated).connect() as connection:
        exists = connection.execute(
            text("select to_regclass('portal.transactions') is not null")
        ).scalar_one()
    assert exists is True


def test_models_match_migrations(migrated):
    with owner(migrated).connect() as connection:
        assert drift(connection, Base.metadata) == []
