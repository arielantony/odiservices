"""PATCH /api/statements/{id}/transactions/{id} with no database (BE-11). The
session is a fake that answers from memory and keeps the writes in the objects,
so no test reaches Postgres."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from server.access import AccessVerifier
from server.db import Category, Statement, Transaction
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import FAKE_USER, NAME, app_with, no_database, serving

HEADER = "Cf-Access-Jwt-Assertion"
CATEGORIES = ("OPERACIONAL", "OUTROS")
ROUTE = "/api/statements/{statement_id}/transactions/{transaction_id}"
NOT_FOUND = {"error": {"code": "statement_not_found", "message": "A fatura não foi encontrada."}}
TRANSACTION_NOT_FOUND = {
    "error": {"code": "transaction_not_found", "message": "A transação não foi encontrada."}
}
INVALID = {"error": {"code": "invalid_statement", "message": "Os dados da fatura são inválidos."}}
UNKNOWN_CATEGORY = {
    "error": {"code": "unknown_category", "message": "A fatura tem uma categoria desconhecida."}
}
TOO_LARGE = {"error": {"code": "payload_too_large", "message": "A fatura enviada é grande demais."}}


class FakeSession:
    """Answers the queries of the route from lists of ORM objects, matched by the
    values each query binds. Writes stay in the objects; commit and rollback do
    nothing."""

    def __init__(self, statements=(), transactions=()):
        self.statements = list(statements)
        self.transactions = list(transactions)

    def scalar(self, query):
        entity = query.column_descriptions[0]["entity"]
        bound = set(query.compile().params.values())
        if entity is Statement:
            return next(
                (s for s in self.statements if s.id in bound and s.user_id in bound), None
            )
        if entity is Transaction:
            return next(
                (t for t in self.transactions if t.id in bound and t.statement_id in bound),
                None,
            )
        if entity is Category:
            return next((code for code in CATEGORIES if code in bound), None)
        raise AssertionError(f"unexpected query on {entity}")

    def commit(self):
        pass

    def rollback(self):
        pass


def seeded(lines=((1, "Loja Exemplo", "1250.00", False), (2, "Compra Exemplo", "20.00", True))):
    """One statement of FAKE_USER with its lines, as (item_number, description,
    amount, doubtful). Every line starts in OUTROS and not reviewed."""
    statement_id = uuid.uuid4()
    statement = Statement(
        id=statement_id,
        user_id=FAKE_USER.id,
        name=NAME,
        total_lanc_atuais=sum((Decimal(amount) for _, _, amount, _ in lines), Decimal("0")),
        created_at=datetime(2026, 11, 10, 14, 3, tzinfo=timezone.utc),
    )
    transactions = [
        Transaction(
            id=uuid.uuid4(),
            statement_id=statement_id,
            item_number=number,
            section="purchases",
            printed_date="05/09",
            description=description,
            amount=Decimal(amount),
            category_code="OUTROS",
            doubtful=doubtful,
            reviewed=False,
        )
        for number, description, amount, doubtful in lines
    ]
    session = FakeSession([statement], transactions)
    return statement_id, [item.id for item in transactions], session


def patch(client, statement_id, transaction_id, body, token=None):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {HEADER: token or make_token(), "content-type": "application/json"}
    url = f"/api/statements/{statement_id}/transactions/{transaction_id}"
    return client.patch(url, content=content, headers=headers)


def test_update_requires_access():
    # A plain app with the real Access chain: no token is refused before any query.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.patch(
        f"/api/statements/{uuid.uuid4()}/transactions/{uuid.uuid4()}",
        json={"reviewed": True},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_ids_are_404():
    client = TestClient(app_with(no_database))
    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = patch(client, raw, uuid.uuid4(), {"reviewed": True})
        assert response.status_code == 404, raw
        assert response.json() == NOT_FOUND

    statement_id, _, session = seeded()
    client = TestClient(app_with(serving(session)))
    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1"):
        response = patch(client, statement_id, raw, {"reviewed": True})
        assert response.status_code == 404, raw
        assert response.json() == TRANSACTION_NOT_FOUND


def test_body_shape_is_422():
    statement_id, transaction_ids, session = seeded()
    client = TestClient(app_with(serving(session)))
    bodies = [
        {},
        {"doubtful": False},
        {"reviewed": "true"},
        {"reviewed": None},
        {"category_code": None},
        {"reviewed": True, "id": 2},
        b"{not json",
        b"[]",
    ]
    for body in bodies:
        response = patch(client, statement_id, transaction_ids[0], body)
        assert response.status_code == 422, body
        assert response.json() == INVALID, body


def test_oversized_body_is_413():
    statement_id, transaction_ids, session = seeded()
    client = TestClient(app_with(serving(session)))
    body = b'{"reviewed": true, "pad": "' + b"a" * 1100 + b'"}'

    response = patch(client, statement_id, transaction_ids[0], body)

    assert response.status_code == 413
    assert response.json() == TOO_LARGE


def test_update_response_headers():
    statement_id, transaction_ids, session = seeded()
    client = TestClient(app_with(serving(session)))

    changed = patch(client, statement_id, transaction_ids[1], {"reviewed": True})
    same = patch(client, statement_id, transaction_ids[1], {"reviewed": True})

    assert changed.status_code == same.status_code == 200
    assert changed.headers["cache-control"] == "no-store"
    assert same.headers["cache-control"] == "no-store"
    data = changed.json()
    assert set(data) == {
        "id", "item_number", "section", "printed_date", "description", "amount",
        "category_code", "doubtful", "reviewed", "moved_by_user",
    }
    assert data["amount"] == "20.00"
    assert data["doubtful"] is True
    assert data["reviewed"] is True


def test_update_logs_carry_no_values(capsys):
    statement_id, transaction_ids, session = seeded(
        [(1, "Loja Exemplo Sigilo", "1234.56", False)]
    )
    client = TestClient(app_with(serving(session)))
    capsys.readouterr()

    response = patch(client, statement_id, transaction_ids[0], {"category_code": "CATEGORIA SIGILO"})
    output = capsys.readouterr().out

    assert response.status_code == 422
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == ROUTE
    assert str(statement_id) not in output
    assert str(transaction_ids[0]) not in output
    assert "Loja Exemplo Sigilo" not in output
    assert "1234.56" not in output
    assert "CATEGORIA SIGILO" not in output


def test_error_bodies_carry_no_payload_value():
    statement_id, transaction_ids, session = seeded()
    client = TestClient(app_with(serving(session)))

    response = patch(client, statement_id, transaction_ids[0], {"category_code": "CATEGORIA SIGILO"})

    assert response.status_code == 422
    assert response.json() == UNKNOWN_CATEGORY
    assert "CATEGORIA SIGILO" not in response.text
