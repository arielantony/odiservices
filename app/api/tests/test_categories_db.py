"""The categories table against a real Postgres (BE-30). Run by make test-db;
the fixtures come from the BE-31 tests."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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

INSERT = text(
    "insert into portal.categories (code, label, auto_assign, position) "
    "values (:c, :l, true, :p)"
)


def test_seed_has_ten_rows_in_order(migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text("select position, code from portal.categories order by position")
        ).all()
    assert [r.position for r in rows] == list(range(1, 11))
    assert rows[0].code == "FORNECEDOR"
    assert rows[-1].code == "OUTROS"


def test_two_categories_are_manual(migrated):
    with owner(migrated).connect() as connection:
        manual = connection.execute(
            text("select code from portal.categories where auto_assign = false order by position")
        ).scalars().all()
    assert manual == ["FOLHA DE PAGAMENTO", "CUSTO DO CARRO"]


def test_lowercase_code_is_refused(migrated):
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(INSERT, {"c": "fornecedor", "l": "Fornecedor", "p": 99})


def test_empty_label_is_refused(migrated):
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(INSERT, {"c": "NOVA", "l": "", "p": 99})


def test_duplicate_position_is_refused(migrated):
    with owner(migrated).begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(INSERT, {"c": "NOVA", "l": "Nova", "p": 1})


def test_app_role_reads_categories(migrated):
    engine = as_role("app_backend", migrated)
    try:
        with engine.connect() as connection:
            count = connection.execute(text("select count(*) from portal.categories")).scalar_one()
    finally:
        engine.dispose()
    assert count == 10


def test_app_role_cannot_write_categories(migrated):
    engine = as_role("app_backend", migrated)
    try:
        with engine.begin() as connection:
            with pytest.raises(Exception, match="permission denied"):
                connection.execute(INSERT, {"c": "NOVA", "l": "Nova", "p": 99})
    finally:
        engine.dispose()


def test_downgrade_drops_the_table(migrated):
    config = alembic_config()
    command.downgrade(config, "0002")
    with owner(migrated).connect() as connection:
        exists = connection.execute(
            text("select to_regclass('portal.categories') is not null")
        ).scalar_one()
    assert exists is False
    command.upgrade(config, "head")
