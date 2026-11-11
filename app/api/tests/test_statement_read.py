"""GET /api/statements/{id} with no database (BE-10). The session is a fake that
answers from memory, or fails on any use, so no test reaches Postgres."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from server.access import AccessVerifier
from server.db import Statement, Transaction
from server.db.session import get_session
from server.main import create_app
from server.settings import Settings
from server.users import current_user
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token

HEADER = "Cf-Access-Jwt-Assertion"
NOT_FOUND = {"error": {"code": "statement_not_found", "message": "A fatura não foi encontrada."}}
DATABASE_UNAVAILABLE = {
    "error": {"code": "database_unavailable", "message": "Não foi possível acessar os dados. Tente novamente."}
}
NAME = "Fatura Cartão Exemplo, set/2026"
FAKE_USER = SimpleNamespace(id=uuid.UUID("00000000-0000-4000-8000-000000000001"))


class NoDatabase:
    """Stands in for the session: any use of the database fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


def no_database():
    yield NoDatabase()


class FakeSession:
    """Answers the two queries of read_statement from lists of ORM objects. A
    query is matched by the values it binds (the ids), not by its SQL."""

    def __init__(self, statements=(), transactions=()):
        self.statements = list(statements)
        self.transactions = list(transactions)

    def scalar(self, query):
        bound = set(query.compile().params.values())
        return next(
            (s for s in self.statements if s.id in bound and s.user_id in bound), None
        )

    def scalars(self, query):
        bound = set(query.compile().params.values())
        return iter([t for t in self.transactions if t.statement_id in bound])


class FailingSession:
    """Every use raises the error a lost connection gives, with a host name in it."""

    def __getattr__(self, name):
        raise OperationalError("select 1", {}, Exception("host 127.0.0.1 refused"))


def failing_session():
    yield FailingSession()


def serving(session):
    """A session dependency that yields `session`."""

    def dependency():
        yield session

    return dependency


def seeded(lines):
    """One statement of FAKE_USER with its lines. `lines` is a list of
    (item_number, description, amount) tuples."""
    statement_id = uuid.uuid4()
    statement = Statement(
        id=statement_id,
        user_id=FAKE_USER.id,
        name=NAME,
        total_lanc_atuais=sum((Decimal(amount) for _, _, amount in lines), Decimal("0")),
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
            doubtful=False,
            reviewed=False,
        )
        for number, description, amount in lines
    ]
    return statement_id, FakeSession([statement], transactions)


def app_with(session_dependency=no_database):
    """The person is not under test here: current_user is replaced. The Access
    check is real, and so is the route."""
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    app.dependency_overrides[current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_session] = session_dependency
    return app


def get(client, statement_id, token=None):
    headers = {HEADER: token or make_token()}
    return client.get(f"/api/statements/{statement_id}", headers=headers)


def test_read_requires_access():
    # A plain app: no override at all, so the real Access chain refuses the
    # request before the route's query could run.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.get(f"/api/statements/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_id_is_404_not_422():
    client = TestClient(app_with())

    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = get(client, raw)
        assert response.status_code == 404, raw
        assert response.json() == NOT_FOUND


def test_read_response_headers():
    statement_id, session = seeded(
        [(1, "Loja Exemplo", "1250.00"), (2, "Estorno Exemplo", "-49.90")]
    )
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["total"] == "1200.10"
    assert isinstance(data["total"], str)
    assert [line["amount"] for line in data["transactions"]] == ["1250.00", "-49.90"]
    assert all(isinstance(line["amount"], str) for line in data["transactions"])
    assert data["created_at"] == "2026-11-10T14:03:00Z"


def test_read_logs_carry_no_description(capsys):
    statement_id, session = seeded([(1, "Loja Exemplo Sigilo", "1234.56")])
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)
    output = capsys.readouterr().out

    assert response.status_code == 200
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements/{statement_id}"
    assert str(statement_id) not in output
    assert "Loja Exemplo Sigilo" not in output
    assert "1234.56" not in output


def test_no_engine_is_503():
    # The real get_session: with no PORTAL_DATABASE_URL it refuses before any query.
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    client = TestClient(app)

    response = get(client, uuid.uuid4())

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE


def test_query_error_is_503_without_details(capsys):
    client = TestClient(app_with(failing_session))

    response = get(client, uuid.uuid4())
    output = capsys.readouterr().out

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE
    assert "127.0.0.1" not in response.text
    assert "127.0.0.1" not in output
    events = [json.loads(line) for line in output.splitlines() if line]
    (failure,) = [event for event in events if event["event"] == "database_error"]
    assert failure["error"] == "OperationalError"
