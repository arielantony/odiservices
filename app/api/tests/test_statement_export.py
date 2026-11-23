"""GET /api/statements/{id}/export with no database (BE-14). The session is the
fake of BE-10 (test_statement_read), so no test reaches Postgres. The pure tests
call render_export directly."""

import json
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from server.access import AccessVerifier
from server.db import Transaction
from server.main import create_app
from server.settings import Settings
from server.statements import SECTIONS, read_payload, render_export
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import (
    DATABASE_UNAVAILABLE,
    NAME,
    app_with,
    failing_session,
    seeded,
    serving,
)

HEADER = "Cf-Access-Jwt-Assertion"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "statement-example-2026-09.json"


def get(client, statement_id, token=None):
    headers = {HEADER: token or make_token()}
    return client.get(f"/api/statements/{statement_id}/export", headers=headers)


def stored(number, description, amount, category="OUTROS", section="purchases", doubtful=False):
    """An unsaved stored line, as the export reads it (the amount has two places)."""
    return Transaction(
        item_number=number,
        section=section,
        printed_date="05/09",
        description=description,
        amount=Decimal(amount),
        category_code=category,
        doubtful=doubtful,
    )


def test_export_requires_access():
    # A plain app: no override at all, so the real Access chain refuses the
    # request before the route's queries could run.
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.get(f"/api/statements/{uuid.uuid4()}/export")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_malformed_id_is_404():
    client = TestClient(app_with())

    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = get(client, raw)
        assert response.status_code == 404, raw
        assert response.json() == {
            "error": {"code": "statement_not_found", "message": "A fatura não foi encontrada."}
        }


def test_export_headers_are_fixed():
    statement_id, session = seeded([(1, "Loja Exemplo", "1250.00")])
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'attachment; filename="fatura.json"'
    headers_text = " ".join(response.headers.values())
    assert NAME not in headers_text
    assert str(statement_id) not in headers_text


def test_money_is_an_unquoted_number():
    statement_id, session = seeded(
        [(1, "Loja Exemplo", "1250.00"), (2, "Loja Exemplo", "10656.35")]
    )
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)
    body = response.text

    assert response.status_code == 200
    assert '"valor": 1250.00' in body
    assert '"total_lanc_atuais": 11906.35' in body
    value = json.loads(body, parse_float=Decimal)["lancamentos"][0]["valor"]
    assert value == Decimal("1250.00")
    assert isinstance(value, Decimal)


def test_export_logs_carry_no_values(capsys):
    statement_id, session = seeded([(1, "Loja Exemplo Sigilo", "1234.56")])
    session.statements[0].name = "Fatura Sigilo"
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)
    output = capsys.readouterr().out

    assert response.status_code == 200
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements/{statement_id}/export"
    assert str(statement_id) not in output
    assert "Fatura Sigilo" not in output
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


def test_rendered_export_passes_the_import_model():
    # The fixture as stored lines (money with two places, as numeric(14,2) gives),
    # rendered and read back by BE-05's reader: the same 17 lines and total.
    data = json.loads(FIXTURE.read_text(encoding="utf-8"), parse_float=Decimal)
    lines = [
        Transaction(
            item_number=item["id"],
            section=SECTIONS[item["secao"]],
            printed_date=item["data"],
            description=item["descricao"],
            amount=item["valor"].quantize(Decimal("0.01")),
            category_code=item["categoria"],
            doubtful=item["duvida"],
        )
        for item in data["lancamentos"]
    ]

    body = render_export(
        NAME,
        Decimal("11906.35"),
        lines,
        card_name=data["cartao_nome"],
        card_last4=data["cartao_final"],
    )
    payload = read_payload(body)

    assert payload.name == NAME
    assert payload.total_lanc_atuais == Decimal("11906.35")
    assert payload.cartao_nome == "Cartão Exemplo"
    assert payload.cartao_final == "0000"
    assert [
        (line.id, line.secao, line.data, line.descricao, line.valor, line.categoria, line.duvida)
        for line in payload.lancamentos
    ] == [
        (item["id"], item["secao"], item["data"], item["descricao"],
         item["valor"].quantize(Decimal("0.01")), item["categoria"], item["duvida"])
        for item in data["lancamentos"]
    ]


def test_text_is_escaped():
    description = 'Loja "Exemplo" \\ barra\nlinha dois'
    body = render_export("Fatura Exemplo", Decimal("5.00"), [stored(1, description, "5.00")])

    payload = read_payload(body)

    assert payload.lancamentos[0].descricao == description


def test_money_has_two_places():
    body = render_export(
        "Fatura Exemplo",
        Decimal("1250.00"),
        [
            stored(1, "Loja Exemplo", "-120"),
            stored(2, "Loja Exemplo", "0.50"),
            stored(3, "Loja Exemplo", "1250.00"),
        ],
    ).decode("utf-8")

    assert '"valor": -120.00' in body
    assert '"valor": 0.50' in body
    assert '"valor": 1250.00' in body
