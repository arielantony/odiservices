"""GET /api/statements/{id}/summary against a real Postgres (BE-12). Run by make
test-db; the app connects as app_backend. The statements are imported through
import_statement (BE-05), so the summary sees what the import writes."""

import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.access import AccessVerifier
from server.db import Statement, Transaction, User, build_engine
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

# The ten rows of spec 5.1: code, total, lines, pending, share.
EXPECTED = [
    ("INVESTIMENTO", "4899.00", 1, 0, 41),
    ("FOLHA DE PAGAMENTO", "3000.00", 1, 0, 25),
    ("FORNECEDOR", "1772.00", 3, 0, 15),
    ("MARKETING/COMERCIAL", "710.00", 2, 0, 6),
    ("DESPESA ADMINISTRATIVA", "682.40", 2, 0, 6),
    ("OPERACIONAL", "548.00", 2, 1, 5),
    ("CUSTO DO CARRO", "305.00", 2, 0, 2),
    ("DESPESAS FINANCEIRAS", "32.25", 2, 0, 0),
    ("PESSOA FISICA", "0.00", 0, 0, None),
    ("OUTROS", "-42.30", 2, 1, None),
]


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


def summary(client, statement_id, headers):
    return client.get(f"/api/statements/{statement_id}/summary", headers=headers)


def line(number, description, amount, category, duvida=False):
    return {
        "id": number,
        "secao": "compras",
        "data": "05/09",
        "descricao": description,
        "valor": amount,
        "categoria": category,
        "duvida": duvida,
    }


def test_fixture_summary_matches_expected_table(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    response = summary(client, imported.id, headers)

    assert response.status_code == 200
    data = response.json()
    rows = [
        (
            row["category_code"],
            row["total"],
            row["transaction_count"],
            row["pending_review_count"],
            row["share"],
        )
        for row in data["categories"]
    ]
    assert rows == EXPECTED
    assert data["lines_total"] == "11906.35"
    assert data["positive_total"] == "11948.65"


def test_bar_and_legend_rule_on_fixture(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    categories = summary(client, imported.id, headers).json()["categories"]

    positive = [row for row in categories if Decimal(row["total"]) > 0]
    assert len(positive) == 8
    assert all(row["category_code"] not in ("PESSOA FISICA", "OUTROS") for row in positive)
    assert [(row["category_code"], row["share"]) for row in positive[:3]] == [
        ("INVESTIMENTO", 41),
        ("FOLHA DE PAGAMENTO", 25),
        ("FORNECEDOR", 15),
    ]
    assert len(positive) - 3 == 5


def test_pending_follows_reviewed(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    with Session(engine) as session:
        item = session.scalar(
            select(Transaction).where(
                Transaction.statement_id == imported.id,
                Transaction.description == "Software Gestão Teste",
            )
        )
        item.reviewed = True
        session.commit()

    categories = summary(client, imported.id, headers).json()["categories"]

    operacional = next(row for row in categories if row["category_code"] == "OPERACIONAL")
    assert operacional["pending_review_count"] == 0
    assert operacional["transaction_count"] == 2


def test_recategorized_line_moves_the_total(client, engine):
    user_id, headers = person(client)
    data = extract()
    for item in data["lancamentos"]:
        if item["id"] == 8:
            item["categoria"] = "FORNECEDOR"
    imported = import_for(engine, user_id, {"name": NAME, **data})

    response = summary(client, imported.id, headers).json()

    first = response["categories"][0]
    assert first["category_code"] == "FORNECEDOR"
    assert first["total"] == "6671.00"
    assert first["transaction_count"] == 4
    assert first["share"] == 56
    investimento = next(
        row for row in response["categories"] if row["category_code"] == "INVESTIMENTO"
    )
    assert investimento["total"] == "0.00"
    assert investimento["share"] is None
    positive = [row for row in response["categories"] if Decimal(row["total"]) > 0]
    assert len(positive) == 7
    assert len(positive) - 3 == 4
    assert response["positive_total"] == "11948.65"
    assert response["lines_total"] == "11906.35"


def test_refund_only_statement_has_no_shares(client, engine):
    user_id, headers = person(client)
    imported = import_for(
        engine,
        user_id,
        {
            "name": "Fatura Estorno Exemplo",
            "total_lanc_atuais": -5.5,
            "lancamentos": [line(1, "Estorno Exemplo", -5.5, "OUTROS")],
        },
    )

    response = summary(client, imported.id, headers).json()

    assert response["positive_total"] == "0.00"
    assert all(row["share"] is None for row in response["categories"])
    assert response["categories"][-1] == {
        "category_code": "OUTROS",
        "position": 10,
        "total": "-5.50",
        "transaction_count": 1,
        "pending_review_count": 0,
        "share": None,
    }


def test_equal_totals_are_ordered_by_position(client, engine):
    user_id, headers = person(client)
    imported = import_for(
        engine,
        user_id,
        {
            "name": "Fatura Empate Exemplo",
            "total_lanc_atuais": 20.0,
            "lancamentos": [
                line(1, "Loja Exemplo", 10.0, "FORNECEDOR"),
                line(2, "Loja Exemplo", 10.0, "OPERACIONAL"),
            ],
        },
    )

    categories = summary(client, imported.id, headers).json()["categories"]

    assert [row["category_code"] for row in categories[:2]] == ["FORNECEDOR", "OPERACIONAL"]
    assert [row["share"] for row in categories[:2]] == [50, 50]


def test_empty_statement_has_ten_zero_rows(client, engine):
    user_id, headers = person(client)
    with Session(engine) as session:
        statement = Statement(user_id=uuid.UUID(user_id), name="Fatura Vazia Exemplo")
        session.add(statement)
        session.commit()
        statement_id = statement.id

    response = summary(client, statement_id, headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["categories"]) == 10
    assert all(row["total"] == "0.00" for row in data["categories"])
    assert all(row["transaction_count"] == 0 for row in data["categories"])
    assert all(row["pending_review_count"] == 0 for row in data["categories"])
    assert all(row["share"] is None for row in data["categories"])
    assert data["lines_total"] == "0.00"
    assert data["positive_total"] == "0.00"


def test_other_users_statement_is_identical_to_missing(client, engine):
    owner_id, owner_headers = person(client)
    imported = import_for(engine, owner_id, {"name": NAME, **extract()})
    _, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")

    other = summary(client, imported.id, other_headers)
    missing = summary(client, uuid.uuid4(), other_headers)

    assert other.status_code == missing.status_code == 404
    assert other.content == missing.content
    without_id = lambda response: {  # noqa: E731
        key: value for key, value in response.headers.items() if key != "x-request-id"
    }
    assert without_id(other) == without_id(missing)
    assert summary(client, imported.id, owner_headers).status_code == 200
