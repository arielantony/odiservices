"""POST /api/statements with no database (BE-05). The session is replaced by
one that fails on any use, so a refused request must never reach it."""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from server.access import AccessVerifier
from server.db.session import get_session
from server.main import create_app
from server.settings import Settings
from server.users import current_user
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_payload import body, extract

HEADER = "Cf-Access-Jwt-Assertion"
INVALID = {"error": {"code": "invalid_statement", "message": "Os dados da fatura são inválidos."}}
FAKE_USER = SimpleNamespace(id=uuid.UUID("00000000-0000-4000-8000-000000000001"))


class NoDatabase:
    """Stands in for the session: any use of the database fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


def no_database():
    yield NoDatabase()


@pytest.fixture
def client():
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    # The person is not under test here: the database is.
    app.dependency_overrides[current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_session] = no_database
    return TestClient(app)


def post(client, data, token=None):
    headers = {HEADER: token or make_token(), "content-type": "application/json"}
    return client.post("/api/statements", content=json.dumps(data), headers=headers)


def test_requires_access(client):
    response = client.post("/api/statements", json=body())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_validation_error_uses_the_portal_format(client):
    # Claim 2 of spec section 8: the RequestValidationError handler answers the
    # portal's format, on this route and on any other route.
    response = post(client, body(total_lanc_atuais="11906.35"))
    assert response.status_code == 422
    assert response.json() == INVALID

    @client.app.get("/api/teste-consulta")
    def consulta(n: int = Query()):
        return {"n": n}

    other = client.get("/api/teste-consulta?n=abc", headers={HEADER: make_token()})
    assert other.status_code == 422
    assert other.json() == INVALID


def test_error_bodies_carry_no_payload_value(client):
    lines = extract()["lancamentos"]
    lines[0].update(
        descricao="Loja Secreta Exemplo", valor=98765.43, categoria="CATEGORIA SECRETA", secao="outros"
    )

    response = post(client, body(lancamentos=lines))

    assert response.status_code == 422
    for planted in ("Loja Secreta Exemplo", "98765.43", "CATEGORIA SECRETA"):
        assert planted not in response.text


def test_oversized_body_is_413(client):
    # Claim 3 of spec section 8: the Content-Length header bounds the body
    # before it is read. The body is not even valid JSON.
    response = client.post(
        "/api/statements",
        content=b"x" * (512 * 1024 + 1),
        headers={HEADER: make_token(), "content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {"code": "payload_too_large", "message": "A fatura enviada é grande demais."}
    }


def test_database_error_on_import_is_503(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def fail(session, user, payload):
        raise OperationalError("select 1", {}, Exception("host 127.0.0.1 refused"))

    monkeypatch.setattr("server.routes.statements.import_statement", fail)

    response = post(client, body())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "127.0.0.1" not in response.text
