"""The users table against a real Postgres (BE-27). Run by make test-db; the
fixtures come from the BE-31 tests."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

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
INSERT = text("insert into portal.users (access_subject, email) values (:s, :e)")


def insert(connection, sub=SUB, email=EMAIL):
    connection.execute(INSERT, {"s": sub, "e": email})


def test_users_table_columns(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema='portal' and table_name='users' order by ordinal_position"
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("id", "uuid", "NO"),
        ("access_subject", "text", "NO"),
        ("email", "text", "NO"),
        ("created_at", "timestamp with time zone", "NO"),
        ("updated_at", "timestamp with time zone", "NO"),
    ]


def test_id_default_generates_v4(migrated):
    with owner(migrated).begin() as connection:
        version = connection.execute(
            text(
                "insert into portal.users (access_subject, email) values (:s, :e) "
                "returning substr(id::text, 15, 1)"
            ),
            {"s": SUB, "e": EMAIL},
        ).scalar_one()
    assert version == "4"


def test_timestamps_default_to_now(migrated):
    from sqlalchemy.orm import Session

    from server.db import User

    with Session(owner(migrated)) as session:
        user = User(access_subject=SUB, email=EMAIL)
        session.add(user)
        session.commit()
        created, updated = user.created_at, user.updated_at
        assert created is not None and updated is not None
        user.email = "outro@exemplo.com"
        session.commit()
        session.refresh(user)
        assert user.updated_at > updated
        assert user.created_at == created


def test_email_must_be_lowercase(migrated):
    with owner(migrated).connect() as connection:
        with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
            insert(connection, email="FULANO@exemplo.com")


@pytest.mark.parametrize(
    ("sub", "email", "name"),
    [
        ("", EMAIL, "ck_users_access_subject_not_empty"),
        (SUB, "", "ck_users_email_not_empty"),
    ],
)
def test_empty_subject_and_email_rejected(migrated, sub, email, name):
    with owner(migrated).connect() as connection:
        with pytest.raises(IntegrityError, match=name):
            insert(connection, sub=sub, email=email)


@pytest.mark.parametrize(
    ("sub", "email", "name"),
    [
        (SUB, "outro@exemplo.com", "uq_users_access_subject"),
        ("sub-outro", EMAIL, "uq_users_email"),
    ],
)
def test_subject_and_email_are_unique(migrated, sub, email, name):
    with owner(migrated).connect() as connection:
        insert(connection)
        with pytest.raises(IntegrityError, match=name):
            insert(connection, sub=sub, email=email)


def test_users_table_is_backend_only(migrated):
    with owner(migrated).connect() as connection:
        assert rls_violations(connection) == []
    with as_role("app_backend", migrated).begin() as connection:
        insert(connection)
        assert connection.execute(text("select count(*) from portal.users")).scalar_one() == 1
        connection.execute(text("update portal.users set access_subject = 'sub-novo'"))
        connection.execute(text("delete from portal.users"))
        assert connection.execute(text("select count(*) from portal.users")).scalar_one() == 0


def test_app_backend_cannot_drop_users(migrated):
    with as_role("app_backend", migrated).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(text("drop table portal.users"))


def test_upgrade_downgrade_upgrade_with_users(database):
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")
    with owner(database).connect() as connection:
        assert connection.execute(text("select to_regclass('portal.users')")).scalar_one()
