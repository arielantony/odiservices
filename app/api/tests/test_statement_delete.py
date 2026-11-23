"""DELETE /api/statements/{id} with no database (BE-15). The session is a fake that
counts what it is asked to do, or fails on any use, so no test reaches Postgres."""

import json
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.access import AccessVerifier
from server.main import create_app
from server.routes import statements as statement_routes
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import (
    DATABASE_UNAVAILABLE,
    FAKE_USER,
    HEADER,
    NOT_FOUND,
    app_with,
    failing_session,
    serving,
)


class FakeDeleteSession:
    """Answers one DELETE with `rows` affected rows and records the calls. The
    bound values of the statement are kept, so a test can see the user filter."""

    def __init__(self, rows: int = 1):
        self.rows = rows
        self.bound: set = set()
        self.deletes = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query):
        self.deletes += 1
        self.bound = set(query.compile().params.values())
        return SimpleNamespace(rowcount=self.rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def delete(client, statement_id, token=None):
    headers = {HEADER: token or make_token()}
    return client.delete(f"/api/statements/{statement_id}", headers=headers)


def test_delete_requires_access(monkeypatch):
    def unreachable(*args):
        raise AssertionError("delete_statement was reached without access")

    monkeypatch.setattr(statement_routes, "delete_statement", unreachable)
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.delete(f"/api/statements/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_id_is_404():
    session = FakeDeleteSession(rows=1)
    client = TestClient(app_with(serving(session)))

    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = delete(client, raw)
        assert response.status_code == 404, raw
        assert response.json() == NOT_FOUND

    assert session.deletes == 0


def test_delete_response_headers():
    session = FakeDeleteSession(rows=1)
    client = TestClient(app_with(serving(session)))

    response = delete(client, uuid.uuid4())

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert session.commits == 1
    assert session.rollbacks == 0
    assert FAKE_USER.id in session.bound


def test_delete_logs_carry_no_values(capsys):
    session = FakeDeleteSession(rows=1)
    client = TestClient(app_with(serving(session)))
    statement_id = uuid.uuid4()

    response = delete(client, statement_id)
    output = capsys.readouterr().out

    assert response.status_code == 204
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements/{statement_id}"
    assert str(statement_id) not in output
    assert "Fatura Sigilo" not in output
    assert "1234.56" not in output


def test_missing_statement_is_404():
    session = FakeDeleteSession(rows=0)
    client = TestClient(app_with(serving(session)))

    response = delete(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert session.rollbacks == 1
    assert session.commits == 0


def test_no_engine_is_503():
    # The real get_session: with no PORTAL_DATABASE_URL it refuses before any query.
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    client = TestClient(app)

    response = delete(client, uuid.uuid4())

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE


def test_query_error_is_503_without_details(capsys):
    client = TestClient(app_with(failing_session))

    response = delete(client, uuid.uuid4())
    output = capsys.readouterr().out

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE
    assert "127.0.0.1" not in response.text
    assert "127.0.0.1" not in output
    events = [json.loads(line) for line in output.splitlines() if line]
    (failure,) = [event for event in events if event["event"] == "database_error"]
    assert failure["error"] == "OperationalError"
