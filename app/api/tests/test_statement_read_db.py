"""GET /api/statements/{id} against a real Postgres (BE-10). Run by make test-db;
the app connects as app_backend. The statements are imported through
import_statement (BE-05), so the read sees what the import writes."""

import json
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from server.access import AccessVerifier
from server.db import Statement, User, build_engine
from server.main import create_app
from server.settings import Settings
from server.statements import import_statement, read_payload
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    url,
)
from test_statement_payload import NAME, extract

pytestmark = pytest.mark.db

HEADER = "Cf-Access-Jwt-Assertion"
GAP_NAME = "Fatura Lacunas Exemplo"


@pytest.fixture
def engine(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD)
    verifier = AccessVerifier(TEAM, AUD, FakeKeyClient())
    return TestClient(create_app(settings, access_verifier=verifier, engine=engine))


def person(client, sub="sub-fulano", email="fulano@exemplo.com") -> tuple[str, dict]:
    """The person's token and the user id, created through /api/me (BE-24)."""
    headers = {HEADER: make_token(sub=sub, email=email)}
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200
    return response.json()["id"], headers


def import_for(engine, user_id: str, data: dict):
    """Import a payload for `user_id` through the BE-05 function."""
    payload = read_payload(json.dumps(data).encode())
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        return import_statement(session, user, payload)


def get(client, statement_id, headers):
    return client.get(f"/api/statements/{statement_id}", headers=headers)


def gap_payload() -> dict:
    """Three fictitious lines: item numbers 1, 2 and 5, total 24.50."""

    def line(number, description, amount):
        return {
            "id": number,
            "secao": "compras",
            "data": "05/09",
            "descricao": description,
            "valor": amount,
            "categoria": "OUTROS",
            "duvida": False,
        }

    return {
        "name": GAP_NAME,
        "total_lanc_atuais": 24.5,
        "lancamentos": [
            line(1, "Loja Exemplo", 10.0),
            line(2, "Loja Exemplo", 20.0),
            line(5, "Estorno Exemplo", -5.5),
        ],
    }


def test_get_canonical_statement_in_order(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    response = get(client, imported.id, headers)

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == NAME
    assert data["total"] == "11906.35"
    assert data["transaction_count"] == 17
    assert data["doubtful_count"] == 2
    lines = data["transactions"]
    assert [line["item_number"] for line in lines] == list(range(1, 18))
    assert [line["description"] for line in lines if line["doubtful"]] == [
        "Software Gestão Teste",
        "Compra Não Identificada",
    ]
    assert all(line["reviewed"] is False for line in lines)
    assert [line["category_code"] for line in lines] == [
        line["categoria"] for line in extract()["lancamentos"]
    ]
    assert data["created_at"].endswith("Z")
    created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
    assert created.utcoffset() == timedelta(0)


def test_gaps_and_money_are_kept_as_stored(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, gap_payload())

    data = get(client, imported.id, headers).json()

    assert [line["item_number"] for line in data["transactions"]] == [1, 2, 5]
    assert [line["amount"] for line in data["transactions"]] == ["10.00", "20.00", "-5.50"]
    assert data["total"] == "24.50"


def test_other_users_statement_is_identical_to_missing(client, engine):
    owner_id, owner_headers = person(client)
    imported = import_for(engine, owner_id, {"name": NAME, **extract()})
    _, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")

    other = get(client, imported.id, other_headers)
    missing = get(client, uuid.uuid4(), other_headers)

    assert other.status_code == missing.status_code == 404
    assert other.content == missing.content
    without_id = lambda response: {  # noqa: E731
        key: value for key, value in response.headers.items() if key != "x-request-id"
    }
    assert without_id(other) == without_id(missing)
    assert get(client, imported.id, owner_headers).status_code == 200


def test_null_total_is_returned_as_null(client, engine):
    user_id, headers = person(client)
    with Session(engine) as session:
        statement = Statement(user_id=uuid.UUID(user_id), name="Fatura Sem Total Exemplo")
        session.add(statement)
        session.commit()
        statement_id = statement.id

    data = get(client, statement_id, headers).json()

    assert data["total"] is None
    assert data["transaction_count"] == 0
    assert data["transactions"] == []
