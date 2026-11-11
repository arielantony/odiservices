"""POST /api/statements against a real Postgres (BE-05). Run by make test-db; the
app connects as app_backend. The fixtures come from the BE-31 tests."""

import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.access import AccessVerifier
from server.db import User, build_engine
from server.main import create_app
from server.settings import Settings
from server.statements import Line, StatementPayload, import_statement
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_statement_payload import NAME, body, extract

pytestmark = pytest.mark.db

HEADER = "Cf-Access-Jwt-Assertion"


@pytest.fixture
def client(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD)
    verifier = AccessVerifier(TEAM, AUD, FakeKeyClient())
    yield TestClient(create_app(settings, access_verifier=verifier, engine=engine))
    engine.dispose()


def post(client, data, token=None):
    headers = {HEADER: token or make_token(), "content-type": "application/json"}
    return client.post("/api/statements", content=json.dumps(data), headers=headers)


def read_numbers(data: dict) -> dict:
    """The JSON numbers read as decimals, as read_payload does."""
    return json.loads(json.dumps(data), parse_float=Decimal)


def counts(database) -> tuple:
    """Rows in statements and in transactions, read as the owner."""
    with owner(database).connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "select (select count(*) from portal.statements), "
                    "(select count(*) from portal.transactions)"
                )
            ).one()
        )


def test_import_canonical_fixture_stores_17_rows(client, migrated):
    response = post(client, body())

    assert response.status_code == 201
    with owner(migrated).connect() as connection:
        (statement,) = connection.execute(
            text("select user_id, name, total_lanc_atuais from portal.statements")
        ).all()
        user_id = connection.execute(text("select id from portal.users")).scalar_one()
        flags = connection.execute(
            text(
                "select count(*), count(*) filter (where doubtful), "
                "count(*) filter (where reviewed) from portal.transactions"
            )
        ).one()
    assert statement.user_id == user_id
    assert statement.name == NAME
    assert statement.total_lanc_atuais == Decimal("11906.35")
    assert tuple(flags) == (17, 2, 0)


def test_section_and_category_are_mapped(client, migrated):
    lines = extract()["lancamentos"]
    lines[0]["categoria"] = "PESSOA FISICA"

    assert post(client, body(lancamentos=lines)).status_code == 201

    with owner(migrated).connect() as connection:
        rows = {
            row.item_number: row
            for row in connection.execute(
                text("select item_number, section, category_code, amount from portal.transactions")
            ).all()
        }
    assert rows[1].section == "purchases" and rows[1].category_code == "PESSOA FISICA"
    assert rows[14].section == "products"
    assert rows[15].section == "international"
    assert rows[2].amount == Decimal("89.90")
    assert rows[15].amount == Decimal("12.35")


def test_unknown_category_stores_nothing(client, migrated):
    lines = extract()["lancamentos"]
    lines[0]["categoria"] = "CATEGORIA INEXISTENTE"

    response = post(client, body(lancamentos=lines))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_category"
    assert counts(migrated) == (0, 0)


def test_total_mismatch_stores_nothing(client, migrated):
    lines = extract()["lancamentos"]
    lines[0]["valor"] = 1249.99

    response = post(client, body(lancamentos=lines))

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "total_mismatch",
            "message": "A soma dos lançamentos não confere com o total da fatura.",
        }
    }
    assert counts(migrated) == (0, 0)


def test_failure_midway_rolls_back(client, migrated):
    user_id = client.get("/api/me", headers={HEADER: make_token()}).json()["id"]
    first = extract()["lancamentos"][0]
    # Two lines with the same item_number: the payload check would refuse it,
    # so the model is built without validation to reach the database.
    lines = [
        Line.model_validate(read_numbers({**first, "id": 1})),
        Line.model_validate(read_numbers({**first, "id": 1, "valor": 10.0})),
    ]
    payload = StatementPayload.model_construct(
        name=NAME, total_lanc_atuais=Decimal("1260.0"), lancamentos=lines
    )
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    try:
        with Session(engine) as session:
            user = session.get(User, uuid.UUID(user_id))
            with pytest.raises(IntegrityError):
                import_statement(session, user, payload)
    finally:
        engine.dispose()

    assert counts(migrated) == (0, 0)


def test_statement_belongs_to_the_token_user(client, migrated):
    response = post(client, body(user_id=str(uuid.uuid4())))
    assert response.status_code == 422
    assert counts(migrated) == (0, 0)

    assert post(client, body()).status_code == 201
    other = make_token(sub="sub-outro", email="outra@exemplo.com")
    assert post(client, body(), token=other).status_code == 201

    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select u.access_subject, count(s.id) from portal.users u "
                "left join portal.statements s on s.user_id = u.id "
                "group by u.access_subject order by u.access_subject"
            )
        ).all()
    assert [tuple(row) for row in rows] == [("sub-fulano", 1), ("sub-outro", 1)]


def test_same_statement_twice_stores_two(client, migrated):
    assert post(client, body()).status_code == 201
    assert post(client, body()).status_code == 201

    assert counts(migrated) == (2, 34)


def test_response_has_counts_and_no_description(client, migrated):
    response = post(client, body())

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"id", "name", "total", "transaction_count", "doubtful_count"}
    assert data["name"] == NAME
    assert data["total"] == "11906.35"
    assert data["transaction_count"] == 17
    assert data["doubtful_count"] == 2
    assert "Distribuidora" not in response.text
    with owner(migrated).connect() as connection:
        stored = connection.execute(text("select id::text from portal.statements")).scalar_one()
    assert data["id"] == stored
