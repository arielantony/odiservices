"""Resolving users against a real Postgres (BE-24). Run by make test-db; the
fixtures come from the BE-31 tests. The app connects as app_backend."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from server import users
from server.access import AccessVerifier
from server.db import build_engine
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_migrations_db import (  # noqa: F401  (fixtures)
    as_role,
    database,
    migrated,
    owner,
    url,
)

pytestmark = pytest.mark.db

HEADER = "Cf-Access-Jwt-Assertion"


@pytest.fixture
def client(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD)
    verifier = AccessVerifier(TEAM, AUD, FakeKeyClient())
    yield TestClient(create_app(settings, access_verifier=verifier, engine=engine))
    engine.dispose()


def get_me(client, **claims):
    return client.get("/api/me", headers={HEADER: make_token(**claims)})


def rows(database):
    with owner(database).connect() as connection:
        return connection.execute(
            text("select id::text, access_subject, email, updated_at from portal.users")
        ).all()


def events(capsys):
    """The user events on stdout, without the request log lines."""
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    return [line for line in lines if line["event"].startswith("user_")]


def test_first_request_creates_the_row(client, migrated, capsys):
    response = get_me(client)

    assert response.status_code == 200
    (row,) = rows(migrated)
    assert response.json() == {"id": row[0]}
    assert row[1:3] == ("sub-fulano", "fulano@exemplo.com")
    assert [e["event"] for e in events(capsys)] == ["user_created"]


def test_second_request_reuses_the_row(client, migrated):
    first = get_me(client).json()
    (before,) = rows(migrated)
    second = get_me(client).json()

    assert first == second
    assert rows(migrated) == [before]


def test_email_is_stored_lowercase(client, migrated):
    get_me(client, email="FULANO@Exemplo.com")

    assert rows(migrated)[0][2] == "fulano@exemplo.com"


def test_email_change_is_flagged_not_applied(client, migrated, capsys):
    first = get_me(client).json()
    (before,) = rows(migrated)
    capsys.readouterr()

    response = get_me(client, email="outro@exemplo.com")

    assert response.status_code == 200
    assert response.json() == first
    assert rows(migrated) == [before]
    (event,) = events(capsys)
    assert event["event"] == "user_email_mismatch"
    assert event["user_id"] == first["id"]
    assert "@" not in json.dumps(event)


def test_same_email_other_subject_is_409(client, migrated, capsys):
    get_me(client)
    capsys.readouterr()

    response = get_me(client, sub="sub-outro")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_conflict"
    assert len(rows(migrated)) == 1
    (event,) = events(capsys)
    assert event["event"] == "user_email_conflict"
    assert set(event) == {"ts", "level", "event"}


def test_token_without_email_and_no_row_is_403(client, migrated):
    response = get_me(client, email=None)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_not_allowed"
    assert rows(migrated) == []


def test_token_without_email_and_existing_row_passes(client, migrated):
    first = get_me(client).json()
    (before,) = rows(migrated)

    response = get_me(client, email=None)

    assert response.status_code == 200
    assert response.json() == first
    assert rows(migrated) == [before]


def test_insert_race_is_absorbed(client, migrated, monkeypatch):
    """The row appears between the SELECT and the INSERT."""
    with owner(migrated).begin() as connection:
        connection.execute(
            text("insert into portal.users (access_subject, email) values (:s, :e)"),
            {"s": "sub-fulano", "e": "fulano@exemplo.com"},
        )
    real = users.find_by_subject
    calls = []

    def blind_first(session, subject):
        calls.append(subject)
        return None if len(calls) == 1 else real(session, subject)

    monkeypatch.setattr(users, "find_by_subject", blind_first)

    response = get_me(client)

    assert response.status_code == 200
    assert response.json() == {"id": rows(migrated)[0][0]}
    assert len(rows(migrated)) == 1


def test_the_app_role_can_resolve(client, migrated):
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text("select current_user")).scalar_one() == "app_backend"

    assert get_me(client).status_code == 200
    assert len(rows(migrated)) == 1
