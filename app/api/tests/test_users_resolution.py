"""Resolving the Access identity to a user, with no database (BE-24)."""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import server.db.session as session_module
from server import users
from server.access import AccessVerifier
from server.db.session import get_session
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token

HEADER = "Cf-Access-Jwt-Assertion"


def build_app(engine=None, verifier=None):
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD)
    verifier = verifier or AccessVerifier(TEAM, AUD, FakeKeyClient())
    return create_app(settings, access_verifier=verifier, engine=engine)


class CountingVerifier(AccessVerifier):
    calls = 0

    def verify(self, token):
        type(self).calls += 1
        return super().verify(token)


def test_me_without_token_is_401():
    # An engine that must never be used: it would fail on connect.
    engine = create_engine("postgresql+psycopg://x@127.0.0.1:1/x")
    response = TestClient(build_app(engine)).get("/api/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_normalize_email():
    assert users.normalize_email(" Fulano@Exemplo.COM ") == "fulano@exemplo.com"
    assert users.normalize_email("   ") is None
    assert users.normalize_email(None) is None


def test_no_database_configured_is_503():
    response = TestClient(build_app()).get("/api/me", headers={HEADER: make_token()})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_database_error_is_503_and_hides_the_driver_message():
    # Nothing listens on port 1 of this machine: the connection is refused.
    engine = create_engine(
        "postgresql+psycopg://x@127.0.0.1:1/x", connect_args={"connect_timeout": 1}
    )
    response = TestClient(build_app(engine)).get("/api/me", headers={HEADER: make_token()})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "127.0.0.1" not in response.text
    assert "refused" not in response.text


def test_session_closed_after_request(monkeypatch):
    closed = []

    class SpySession(session_module.Session):
        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(session_module, "Session", SpySession)
    engine = create_engine("postgresql+psycopg://x@127.0.0.1:1/x")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))

    generator = get_session(request)
    next(generator)
    assert closed == []
    try:
        generator.throw(RuntimeError("the route failed"))
    except RuntimeError:
        pass
    assert closed == [True]


def test_flags_have_no_personal_data(capsys):
    users.log_event("WARNING", "user_email_mismatch", user_id="id-ficticio")
    users.log_event("WARNING", "user_email_conflict")

    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines()]
    assert [line["event"] for line in lines] == ["user_email_mismatch", "user_email_conflict"]
    assert "@" not in out
    assert "sub-" not in out


def test_the_token_is_verified_once_per_request():
    CountingVerifier.calls = 0
    verifier = CountingVerifier(TEAM, AUD, FakeKeyClient())
    # No engine: the request ends in a 503, after both dependencies ran.
    TestClient(build_app(verifier=verifier)).get("/api/me", headers={HEADER: make_token()})

    assert CountingVerifier.calls == 1
