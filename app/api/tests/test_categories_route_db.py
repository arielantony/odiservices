"""GET /api/categories against a real Postgres (BE-16). Run by make test-db;
the app connects as app_backend. The rows are the seed of BE-30, migrated by
the BE-31 fixtures."""

import importlib

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from server.access import AccessVerifier
from server.db import build_engine
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)

pytestmark = pytest.mark.db

SEED = importlib.import_module("migrations.versions.0003_categories").SEED
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


def get_categories(client):
    return client.get("/api/categories", headers={HEADER: make_token()})


def test_labels_match_the_seed_in_position_order(client):
    response = get_categories(client)

    assert response.status_code == 200
    expected = [
        {"code": code, "label": label, "position": position}
        for position, (code, label, _) in enumerate(SEED, start=1)
    ]
    assert response.json() == expected


def test_order_is_position_not_code(client):
    codes = [item["code"] for item in get_categories(client).json()]

    assert codes[0] == "FORNECEDOR"
    assert codes[-1] == "OUTROS"
    assert codes != sorted(codes)


def test_response_equals_the_table(client, migrated):
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text("select code, label, position from portal.categories order by position")
        ).all()
    expected = [{"code": r.code, "label": r.label, "position": r.position} for r in rows]

    assert get_categories(client).json() == expected
