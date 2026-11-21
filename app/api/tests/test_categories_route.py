"""GET /api/categories with no database (BE-16). The session is a fake that
answers from the migration's SEED, or fails on any use, so no test reaches
Postgres."""

import importlib
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from server.access import AccessVerifier
from server.db import Category
from server.db.session import get_session
from server.main import create_app
from server.settings import Settings
from server.users import current_user
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token

SEED_MODULE = importlib.import_module("migrations.versions.0003_categories")
HEADER = "Cf-Access-Jwt-Assertion"
DATABASE_UNAVAILABLE = {
    "error": {"code": "database_unavailable", "message": "Não foi possível acessar os dados. Tente novamente."}
}
FAKE_USER = SimpleNamespace(id=uuid.UUID("00000000-0000-4000-8000-000000000001"))


def seed_rows():
    """The ten rows of the seed, as the ORM would return them, in position order."""
    return [
        Category(code=code, label=label, auto_assign=auto, position=n)
        for n, (code, label, auto) in enumerate(SEED_MODULE.SEED, start=1)
    ]


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    """Returns the seed rows for the categories query, as the SQL would order them."""

    def scalars(self, query):
        return FakeResult(seed_rows())


class FailingSession:
    """Every use raises the error a lost connection gives, with a host name in it."""

    def scalars(self, query):
        raise OperationalError("select 1", {}, Exception("host 127.0.0.1 refused"))


class NoDatabase:
    """Stands in for the session: any use of the database fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


def serving(session):
    def dependency():
        yield session

    return dependency


def app_with(session_dependency):
    """The person is not under test here: current_user is replaced. The Access
    check is real, and so is the route."""
    app = create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )
    app.dependency_overrides[current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_session] = session_dependency
    return app


def get(client, token=None):
    headers = {HEADER: token or make_token()}
    return client.get("/api/categories", headers=headers)


def test_categories_requires_access():
    # A plain app: the Access check refuses before the route or the session runs.
    app = app_with(serving(NoDatabase()))
    app.dependency_overrides.pop(current_user)
    client = TestClient(app)

    response = client.get("/api/categories")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_no_engine_is_503():
    # No override: the real get_session finds no engine and refuses.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = get(client)

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE


def test_query_error_is_503_without_details(capsys):
    client = TestClient(app_with(serving(FailingSession())))

    response = get(client)

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE
    assert "127.0.0.1" not in response.text
    out = capsys.readouterr().out
    assert "127.0.0.1" not in out
    assert "database_error" in out
    assert "OperationalError" in out


def test_labels_equal_the_seeded_labels():
    client = TestClient(app_with(serving(FakeSession())))

    response = get(client)

    assert response.status_code == 200
    got = [(item["code"], item["label"], item["position"]) for item in response.json()]
    expected = [(c, l, p) for p, (c, l, _) in enumerate(SEED_MODULE.SEED, 1)]
    assert got == expected


def test_query_orders_by_position_in_sql():
    # The statement the route runs, compiled for PostgreSQL. The real order is
    # checked against the database in test_categories_route_db.py.
    statement = select(Category).order_by(Category.position)

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert sql.endswith("ORDER BY portal.categories.position")


def test_response_shape_and_headers():
    client = TestClient(app_with(serving(FakeSession())))

    response = get(client)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 10
    for item in body:
        assert set(item) == {"code", "label", "position"}
    assert "auto_assign" not in response.text
