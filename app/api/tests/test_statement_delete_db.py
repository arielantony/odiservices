"""DELETE /api/statements/{id} against a real Postgres (BE-15). Run by make test-db;
the app connects as app_backend. The statements are imported through
import_statement (BE-05), and the rows are checked as the owner, so the test sees
what the database kept."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.access import AccessVerifier
from server.db import Statement, Transaction, build_engine
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_statement_payload import NAME, extract
from test_statement_read_db import GAP_NAME, gap_payload, import_for, person

pytestmark = pytest.mark.db


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


def delete(client, statement_id, headers):
    return client.delete(f"/api/statements/{statement_id}", headers=headers)


def get(client, statement_id, headers):
    return client.get(f"/api/statements/{statement_id}", headers=headers)


def stored(database, statement_id):
    """The statement row and its line count, read as the owner."""
    with Session(owner(database)) as session:
        row = session.get(Statement, statement_id)
        lines = list(
            session.scalars(
                select(Transaction).where(Transaction.statement_id == statement_id)
            )
        )
        return row, len(lines)


def test_delete_removes_statement_and_its_transactions(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    assert imported.transaction_count == 17

    response = delete(client, imported.id, headers)

    assert response.status_code == 204
    assert response.content == b""
    row, lines = stored(migrated, imported.id)
    assert row is None
    assert lines == 0
    assert get(client, imported.id, headers).status_code == 404


def test_other_users_statement_is_404_and_kept(client, engine, migrated):
    owner_id, owner_headers = person(client)
    imported = import_for(engine, owner_id, {"name": NAME, **extract()})
    _, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")

    other = delete(client, imported.id, other_headers)
    random_id = delete(client, uuid.uuid4(), other_headers)

    assert other.status_code == random_id.status_code == 404
    assert other.content == random_id.content
    without_id = lambda response: {  # noqa: E731
        key: value for key, value in response.headers.items() if key != "x-request-id"
    }
    assert without_id(other) == without_id(random_id)
    row, lines = stored(migrated, imported.id)
    assert row is not None
    assert lines == 17
    assert get(client, imported.id, owner_headers).status_code == 200


def test_second_delete_is_404(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    unknown = delete(client, uuid.uuid4(), headers)

    first = delete(client, imported.id, headers)
    second = delete(client, imported.id, headers)

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.content == unknown.content


def test_delete_leaves_other_statements_alone(client, engine, migrated):
    user_id, headers = person(client)
    first = import_for(engine, user_id, {"name": NAME, **extract()})
    second = import_for(engine, user_id, gap_payload())

    response = delete(client, first.id, headers)

    assert response.status_code == 204
    kept = get(client, second.id, headers).json()
    assert kept["name"] == GAP_NAME
    assert [line["item_number"] for line in kept["transactions"]] == [1, 2, 5]
    assert kept["total"] == "24.50"
    row, lines = stored(migrated, second.id)
    assert row is not None
    assert lines == 3
