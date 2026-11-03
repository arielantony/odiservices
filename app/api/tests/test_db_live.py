import pytest
from pydantic import SecretStr
from sqlalchemy import text

from server.db import build_engine, check_database

pytestmark = pytest.mark.db

URL = SecretStr("postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices")


def test_local_postgres_answers():
    assert check_database(build_engine(URL)).role == "odiservices"


def test_prepared_statements_off():
    engine = build_engine(URL)
    with engine.connect() as connection:
        for _ in range(8):
            connection.execute(text("select 1"))
        count = connection.execute(
            text("select count(*) from pg_prepared_statements")
        ).scalar_one()
    assert count == 0
