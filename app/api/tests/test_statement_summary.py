"""GET /api/statements/{id}/summary with no database (BE-12). The session answers
the statement lookup from memory and the totals query from a list of rows, or
fails on any use, so no test reaches Postgres."""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.access import AccessVerifier
from server.db import Statement
from server.main import create_app
from server.settings import Settings
from server.statements import summary_view
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import (
    DATABASE_UNAVAILABLE,
    FAKE_USER,
    FakeSession,
    NAME,
    NOT_FOUND,
    app_with,
    failing_session,
    serving,
)

HEADER = "Cf-Access-Jwt-Assertion"

# (code, position, total, lines, pending): the ten rows of the canonical fixture
# (spec 5.1), in the order the summary returns them.
FIXTURE_ROWS = [
    ("FORNECEDOR", 1, Decimal("1772.00"), 3, 0),
    ("OPERACIONAL", 2, Decimal("548.00"), 2, 1),
    ("MARKETING/COMERCIAL", 3, Decimal("710.00"), 2, 0),
    ("INVESTIMENTO", 4, Decimal("4899.00"), 1, 0),
    ("DESPESA ADMINISTRATIVA", 5, Decimal("682.40"), 2, 0),
    ("FOLHA DE PAGAMENTO", 6, Decimal("3000.00"), 1, 0),
    ("CUSTO DO CARRO", 7, Decimal("305.00"), 2, 0),
    ("DESPESAS FINANCEIRAS", 8, Decimal("32.25"), 2, 0),
    ("PESSOA FISICA", 9, Decimal("0.00"), 0, 0),
    ("OUTROS", 10, Decimal("-42.30"), 2, 1),
]


class SummarySession(FakeSession):
    """FakeSession that also answers the totals query with `rows`."""

    def __init__(self, statement, rows):
        super().__init__([statement])
        self.rows = list(rows)

    def execute(self, query):
        return SimpleNamespace(all=lambda: list(self.rows))


def statement_with(rows):
    """One statement of FAKE_USER whose totals query answers `rows`."""
    statement_id = uuid.uuid4()
    statement = Statement(id=statement_id, user_id=FAKE_USER.id, name=NAME)
    return statement_id, SummarySession(statement, rows)


def get(client, statement_id, token=None):
    headers = {HEADER: token or make_token()}
    return client.get(f"/api/statements/{statement_id}/summary", headers=headers)


def test_summary_requires_access():
    # A plain app: no override at all, so the real Access chain refuses the
    # request before the route's queries could run.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.get(f"/api/statements/{uuid.uuid4()}/summary")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_id_is_404():
    client = TestClient(app_with(serving(SummarySession(None, []))))

    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = get(client, raw)
        assert response.status_code == 404, raw
        assert response.json() == NOT_FOUND


def test_summary_response_headers():
    statement_id, session = statement_with(FIXTURE_ROWS)
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["lines_total"] == "11906.35"
    assert data["positive_total"] == "11948.65"
    by_code = {row["category_code"]: row for row in data["categories"]}
    assert by_code["INVESTIMENTO"]["total"] == "4899.00"
    assert by_code["OUTROS"]["total"] == "-42.30"
    assert all(isinstance(row["total"], str) for row in data["categories"])
    assert all(
        row["share"] is None or isinstance(row["share"], int) for row in data["categories"]
    )
    assert by_code["PESSOA FISICA"]["share"] is None


def test_summary_logs_carry_no_values(capsys):
    statement_id, session = statement_with([("CATEGORIA SIGILO", 1, Decimal("1234.56"), 1, 0)])
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)
    output = capsys.readouterr().out

    assert response.status_code == 200
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements/{statement_id}/summary"
    assert str(statement_id) not in output
    assert "CATEGORIA SIGILO" not in output
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


def test_shares_are_largest_remainder():
    view = summary_view(FIXTURE_ROWS)

    assert [row.category_code for row in view.categories][:3] == [
        "INVESTIMENTO",
        "FOLHA DE PAGAMENTO",
        "FORNECEDOR",
    ]
    assert [row.share for row in view.categories] == [41, 25, 15, 6, 6, 5, 2, 0, None, None]
    assert sum(row.share for row in view.categories if row.share is not None) == 100
    assert view.positive_total == "11948.65"
    assert view.lines_total == "11906.35"


def test_no_positive_total_has_no_shares():
    view = summary_view(
        [
            ("OUTROS", 10, Decimal("-5.50"), 1, 0),
            ("PESSOA FISICA", 9, Decimal("0.00"), 0, 0),
        ]
    )

    assert view.positive_total == "0.00"
    assert [row.share for row in view.categories] == [None, None]
    assert view.lines_total == "-5.50"


def test_ties_are_ordered_by_position():
    view = summary_view(
        [
            ("OPERACIONAL", 2, Decimal("10.00"), 1, 0),
            ("FORNECEDOR", 1, Decimal("10.00"), 1, 0),
        ]
    )

    assert [row.category_code for row in view.categories] == ["FORNECEDOR", "OPERACIONAL"]
    assert [row.share for row in view.categories] == [50, 50]


def test_empty_totals_are_zero():
    rows = [(code, position, Decimal("0"), 0, 0) for code, position, _, _, _ in FIXTURE_ROWS]

    view = summary_view(rows)

    assert len(view.categories) == 10
    assert all(row.total == "0.00" for row in view.categories)
    assert all(row.share is None for row in view.categories)
    assert view.lines_total == "0.00"
    assert view.positive_total == "0.00"


def test_equal_remainders_go_to_lower_position():
    view = summary_view(
        [
            ("FORNECEDOR", 1, Decimal("1.00"), 1, 0),
            ("OPERACIONAL", 2, Decimal("1.00"), 1, 0),
            ("MARKETING/COMERCIAL", 3, Decimal("1.00"), 1, 0),
        ]
    )

    shares = [row.share for row in view.categories]
    assert shares == [34, 33, 33]
    assert sum(shares) == 100
