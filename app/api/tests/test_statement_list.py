"""GET /api/statements with no database (BE-06). The session is a fake that
answers the page query from a list of rows and records every query, so no test
reaches Postgres."""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from server.access import AccessVerifier
from server.main import create_app
from server.settings import Settings
from server.statements import encode_cursor
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import HEADER, NAME, app_with, serving

DATABASE_UNAVAILABLE = {
    "error": {"code": "database_unavailable", "message": "Não foi possível acessar os dados. Tente novamente."}
}
NEWEST = datetime(2026, 11, 10, 14, 3, tzinfo=timezone.utc)


class ListSession:
    """Answers execute() with `rows`, or raises `error`. Every query is recorded."""

    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.error = error
        self.queries = []

    def execute(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(all=lambda: list(self.rows))


def serving_list(session):
    def dependency():
        yield session

    return dependency


def row(index, name=NAME, total=Decimal("11906.35"), card_name=None, card_last4=None,
        status="ready", failure_code=None, transactions=17, pending=2):
    """One row of the page query, as the database returns it. Row 0 is the newest."""
    return SimpleNamespace(
        id=uuid.UUID(int=index + 1),
        name=name,
        total_lanc_atuais=total,
        card_name=card_name,
        card_last4=card_last4,
        status=status,
        failure_code=failure_code,
        created_at=NEWEST - timedelta(minutes=index),
        transaction_count=transactions,
        pending_review_count=pending,
    )


def listing(client, query="", token=None):
    headers = {HEADER: token or make_token()}
    return client.get(f"/api/statements{query}", headers=headers)


def raw_cursor(body) -> str:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


VALID_ID = str(uuid.UUID(int=99))


def test_list_requires_access():
    # A plain app with no override: the real Access chain refuses the request
    # before the page query could run.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.get("/api/statements")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "query",
    ["?limit=0", "?limit=101", "?limit=-1", "?limit=1.5", "?limit=abc", "?limit=", "?limit=5&limit=6"],
)
def test_invalid_limit_is_422(query):
    session = ListSession()
    client = TestClient(app_with(serving(session)))

    response = listing(client, query)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_limit"
    assert session.queries == []


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!!",
        base64.urlsafe_b64encode(b"[]").rstrip(b"=").decode(),
        raw_cursor({"v": 1, "t": "2026-08-04T18:05:00+00:00"}),
        raw_cursor({"v": 1, "t": "2026-08-04T18:05:00+00:00", "i": VALID_ID, "x": 1}),
        raw_cursor({"v": 1, "t": "2026-08-04T18:05:00", "i": VALID_ID}),
        raw_cursor({"v": 1, "t": "2026-08-04T18:05:00+00:00", "i": "not-a-uuid"}),
        raw_cursor({"v": 2, "t": "2026-08-04T18:05:00+00:00", "i": VALID_ID}),
        raw_cursor({"v": True, "t": "2026-08-04T18:05:00+00:00", "i": VALID_ID}),
        "A" * 513,
    ],
)
def test_invalid_cursor_is_422(cursor):
    session = ListSession()
    client = TestClient(app_with(serving(session)))

    response = listing(client, f"?cursor={cursor}")

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_cursor", "message": "O cursor da página não é válido."}
    }
    assert session.queries == []


def test_repeated_cursor_is_422():
    session = ListSession()
    client = TestClient(app_with(serving(session)))
    cursor = encode_cursor(NEWEST, uuid.UUID(int=1))

    response = listing(client, f"?cursor={cursor}&cursor={cursor}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"
    assert session.queries == []


def test_list_response_headers():
    session = ListSession([row(0, card_name="Cartão Exemplo", card_last4="0000"), row(1, total=None)])
    client = TestClient(app_with(serving_list(session)))

    response = listing(client, "?limit=1")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["items"][0]["total"] == "11906.35"
    assert isinstance(data["items"][0]["total"], str)
    assert data["items"][0]["created_at"] == "2026-11-10T14:03:00Z"
    assert data["items"][0]["card_name"] == "Cartão Exemplo"
    assert data["items"][0]["card_last4"] == "0000"
    assert data["items"][0]["status"] == "ready"
    assert data["items"][0]["failure_code"] is None
    assert data["items"][0]["failure_message"] is None
    assert len(data["items"]) == 1
    assert isinstance(data["next_cursor"], str)


def test_list_logs_carry_no_values(capsys):
    session = ListSession(
        [row(0, name="Fatura Sigilo Exemplo", total=Decimal("1234.56")), row(1)]
    )
    client = TestClient(app_with(serving_list(session)))
    cursor = encode_cursor(NEWEST, uuid.UUID(int=1))

    response = listing(client, f"?limit=7&cursor={cursor}")
    output = capsys.readouterr().out

    assert response.status_code == 200
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements"
    assert "Fatura Sigilo Exemplo" not in output
    assert "1234.56" not in output
    assert "limit=7" not in output
    assert "cursor=" not in output
    assert cursor not in output


def test_default_limit_is_20():
    session = ListSession([row(index) for index in range(25)])
    client = TestClient(app_with(serving_list(session)))

    response = listing(client)

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 20
    assert isinstance(data["next_cursor"], str)


def test_no_engine_is_503():
    # The real get_session: with no PORTAL_DATABASE_URL it refuses before any query.
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    client = TestClient(app)

    response = listing(client)

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE


def test_query_error_is_503_without_details(capsys):
    error = OperationalError("select 1", {}, Exception("host 127.0.0.1 refused"))
    client = TestClient(app_with(serving_list(ListSession(error=error))))

    response = listing(client)
    output = capsys.readouterr().out

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE
    assert "127.0.0.1" not in response.text
    assert "127.0.0.1" not in output
    events = [json.loads(line) for line in output.splitlines() if line]
    (failure,) = [event for event in events if event["event"] == "database_error"]
    assert failure["error"] == "OperationalError"
