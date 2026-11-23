"""GET /api/statements/{id}/export against a real Postgres (BE-14). Run by make
test-db; the app connects as app_backend. The statements are imported through
import_statement (BE-05), so the export reads what the import writes, and the
file is read back through BE-05 and imported again."""

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


def export(client, statement_id, headers):
    return client.get(f"/api/statements/{statement_id}/export", headers=headers)


def stored_lines(engine, statement_id):
    with Session(engine) as session:
        items = session.scalars(
            select(Transaction)
            .where(Transaction.statement_id == statement_id)
            .order_by(Transaction.item_number)
        )
        return [
            (
                item.item_number,
                item.section,
                item.printed_date,
                item.description,
                item.amount,
                item.category_code,
                item.doubtful,
            )
            for item in items
        ]


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


def test_fixture_round_trips_through_the_import(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    response = export(client, imported.id, headers)

    assert response.status_code == 200
    payload = read_payload(response.content)
    assert payload.name == NAME
    assert payload.cartao_nome == "Cartão Exemplo"
    assert payload.cartao_final == "0000"
    again = import_statement_payload(engine, user_id, payload)
    assert again.total == Decimal("11906.35")
    assert stored_lines(engine, again.id) == stored_lines(engine, imported.id)
    with Session(engine) as session:
        copy = session.get(Statement, again.id)
        assert (copy.name, copy.card_name, copy.card_last4) == (
            NAME,
            "Cartão Exemplo",
            "0000",
        )
    doubtful = [item for item in stored_lines(engine, again.id) if item[6]]
    assert [item[3] for item in doubtful] == ["Software Gestão Teste", "Compra Não Identificada"]


def import_statement_payload(engine, user_id: str, payload):
    """Import an already-read payload for `user_id` (BE-05)."""
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        return import_statement(session, user, payload)


def test_moved_line_is_exported_in_its_new_category(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    with Session(engine) as session:
        item = session.scalar(
            select(Transaction).where(
                Transaction.statement_id == imported.id,
                Transaction.description == "Correios Demo",
            )
        )
        item.category_code = "OPERACIONAL"
        session.commit()

    response = export(client, imported.id, headers)

    assert response.status_code == 200
    moved = [
        entry
        for entry in json.loads(response.content, parse_float=Decimal)["lancamentos"]
        if entry["descricao"] == "Correios Demo"
    ]
    assert [entry["categoria"] for entry in moved] == ["OPERACIONAL"]
    again = import_statement_payload(engine, user_id, read_payload(response.content))
    kept = [item for item in stored_lines(engine, again.id) if item[3] == "Correios Demo"]
    assert [item[5] for item in kept] == ["OPERACIONAL"]


def test_exact_cents_survive_the_round_trip(client, engine):
    user_id, headers = person(client)
    imported = import_for(
        engine,
        user_id,
        {
            "name": "Fatura Centavos Exemplo",
            "total_lanc_atuais": 0.30,
            "lancamentos": [
                line(1, "Loja Exemplo", 0.10, "FORNECEDOR"),
                line(2, "Loja Exemplo", 0.20, "FORNECEDOR"),
            ],
        },
    )

    response = export(client, imported.id, headers)

    assert response.status_code == 200
    assert b'"valor": 0.10' in response.content
    assert b'"valor": 0.20' in response.content
    assert b'"total_lanc_atuais": 0.30' in response.content
    again = import_statement_payload(engine, user_id, read_payload(response.content))
    assert again.total == Decimal("0.30")


def test_empty_or_untotalled_statement_is_409(client, engine):
    user_id, headers = person(client)
    with Session(engine) as session:
        empty = Statement(
            user_id=uuid.UUID(user_id), name="Fatura Vazia Exemplo", total_lanc_atuais=Decimal("0")
        )
        untotalled = Statement(user_id=uuid.UUID(user_id), name="Fatura Sem Total Exemplo")
        processing = Statement(
            user_id=uuid.UUID(user_id),
            name="Fatura Em Processo Exemplo",
            total_lanc_atuais=Decimal("10.00"),
            status="processing",
        )
        session.add_all([empty, untotalled, processing])
        session.flush()
        for statement_id in (untotalled.id, processing.id):
            session.add(
                Transaction(
                    statement_id=statement_id,
                    item_number=1,
                    section="purchases",
                    printed_date="05/09",
                    description="Loja Exemplo",
                    amount=Decimal("10.00"),
                    category_code="FORNECEDOR",
                    original_category_code="FORNECEDOR",
                )
            )
        session.commit()
        ids = [empty.id, untotalled.id, processing.id]

    for statement_id in ids:
        response = export(client, statement_id, headers)
        assert response.status_code == 409, statement_id
        assert response.json() == {
            "error": {
                "code": "statement_not_exportable",
                "message": "Esta fatura não pode ser exportada: ela não tem lançamentos ou um total.",
            }
        }
        assert response.headers["cache-control"] == "no-store"


def test_sum_mismatch_is_409(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    with Session(engine) as session:
        item = session.scalar(
            select(Transaction).where(
                Transaction.statement_id == imported.id,
                Transaction.description == "Distribuidora Exemplo Ltda",
            )
        )
        item.amount = item.amount + Decimal("0.01")
        session.commit()

    response = export(client, imported.id, headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "statement_not_exportable"


def test_other_users_statement_is_identical_to_missing(client, engine):
    owner_id, owner_headers = person(client)
    imported = import_for(engine, owner_id, {"name": NAME, **extract()})
    _, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")

    other = export(client, imported.id, other_headers)
    missing = export(client, uuid.uuid4(), other_headers)

    assert other.status_code == missing.status_code == 404
    assert other.content == missing.content
    without_id = lambda response: {  # noqa: E731
        key: value for key, value in response.headers.items() if key != "x-request-id"
    }
    assert without_id(other) == without_id(missing)
    assert export(client, imported.id, owner_headers).status_code == 200
