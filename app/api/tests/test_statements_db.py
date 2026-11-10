"""The statements table against a real Postgres (BE-28). Run by make test-db; the
fixtures come from the BE-31 tests."""

from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from server.db import Base, Statement, User
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
INSERT_STATEMENT = text("insert into portal.statements (user_id, name) values (:u, :n)")


def make_user(connection) -> str:
    return connection.execute(
        text(
            "insert into portal.users (access_subject, email) values (:s, :e) returning id"
        ),
        {"s": SUB, "e": EMAIL},
    ).scalar_one()


def test_statements_columns(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema='portal' and table_name='statements' order by ordinal_position"
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("id", "uuid", "NO"),
        ("user_id", "uuid", "NO"),
        ("name", "text", "NO"),
        ("total_lanc_atuais", "numeric", "YES"),
        ("created_at", "timestamp with time zone", "NO"),
        ("updated_at", "timestamp with time zone", "NO"),
    ]


def test_defaults_are_set_on_insert(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        row = connection.execute(
            text(
                "insert into portal.statements (user_id, name) values (:u, :n) "
                "returning substr(id::text, 15, 1) as version, created_at, updated_at, "
                "total_lanc_atuais"
            ),
            {"u": user_id, "n": NAME},
        ).one()
    assert row.version == "4"
    assert row.created_at is not None and row.updated_at is not None
    assert row.total_lanc_atuais is None


def test_updated_at_moves_on_orm_update(migrated):
    with Session(owner(migrated)) as session:
        user = User(access_subject=SUB, email=EMAIL)
        session.add(user)
        session.commit()
        statement = Statement(user_id=user.id, name=NAME)
        session.add(statement)
        session.commit()
        updated = statement.updated_at
        statement.name = "Fatura Cartão Exemplo, out/2026"
        session.commit()
        session.refresh(statement)
        assert statement.updated_at > updated


def test_empty_name_is_refused(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="ck_statements_name_not_empty"):
            connection.execute(INSERT_STATEMENT, {"u": user_id, "n": ""})


def test_unknown_user_is_refused(migrated):
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="fk_statements_user_id_users"):
            connection.execute(
                INSERT_STATEMENT,
                {"u": "00000000-0000-4000-8000-000000000000", "n": NAME},
            )


def test_user_with_statements_cannot_be_deleted(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        connection.execute(INSERT_STATEMENT, {"u": user_id, "n": NAME})
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError, match="fk_statements_user_id_users"):
            connection.execute(text("delete from portal.users"))


def test_total_keeps_two_decimals(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
        connection.execute(
            text(
                "insert into portal.statements (user_id, name, total_lanc_atuais) "
                "values (:u, :n, :t), (:u, :n, :neg)"
            ),
            {"u": user_id, "n": NAME, "t": Decimal("11906.35"), "neg": Decimal("-120.00")},
        )
    with owner(migrated).connect() as connection:
        totals = connection.execute(
            text("select total_lanc_atuais from portal.statements order by total_lanc_atuais desc")
        ).scalars().all()
    assert totals == [Decimal("11906.35"), Decimal("-120.00")]


def test_app_role_reads_and_writes_statements(migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
    with as_role("app_backend", migrated).begin() as connection:
        connection.execute(INSERT_STATEMENT, {"u": user_id, "n": NAME})
        count = connection.execute(text("select count(*) from portal.statements")).scalar_one()
        assert count == 1
        connection.execute(text("update portal.statements set name = 'Fatura Exemplo, out/2026'"))
        connection.execute(text("delete from portal.statements"))
        count = connection.execute(text("select count(*) from portal.statements")).scalar_one()
        assert count == 0


def test_app_role_cannot_drop_statements(migrated):
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("drop table portal.statements"))


def test_downgrade_drops_the_table(migrated):
    config = alembic_config()
    command.downgrade(config, "0003")
    with owner(migrated).connect() as connection:
        exists = connection.execute(
            text("select to_regclass('portal.statements') is not null")
        ).scalar_one()
    assert exists is False
    command.upgrade(config, "head")
    with owner(migrated).connect() as connection:
        exists = connection.execute(
            text("select to_regclass('portal.statements') is not null")
        ).scalar_one()
    assert exists is True


def test_models_match_migrations(migrated):
    with owner(migrated).connect() as connection:
        assert drift(connection, Base.metadata) == []
