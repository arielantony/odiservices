"""The statement payload and its checks, with no database (BE-05)."""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.statements import StatementPayload, lines_total, read_payload

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "statement-example-2026-09.json"
NAME = "Fatura Cartão Exemplo, set/2026"


def extract() -> dict:
    """The canonical extraction (no name), read fresh for each test."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def body(**changes) -> dict:
    """The canonical statement with its name, changed in memory."""
    data = {"name": NAME, **extract()}
    data.update(changes)
    return data


def parse(data: dict) -> StatementPayload:
    # The route reads the body as bytes, so the tests do too.
    return read_payload(json.dumps(data).encode())


def test_fixture_validates():
    model = parse(body())

    assert len(model.lancamentos) == 17
    assert lines_total(model.lancamentos) == model.total_lanc_atuais == Decimal("11906.35")
    assert sum(line.duvida for line in model.lancamentos) == 2


def test_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        parse(body(user_id="00000000-0000-4000-8000-000000000000"))

    lines = extract()["lancamentos"]
    lines[0]["extra"] = "x"
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_duplicate_ids_are_refused():
    lines = extract()["lancamentos"]
    lines[1]["id"] = 1

    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_id_zero_is_refused():
    lines = extract()["lancamentos"]
    lines[0]["id"] = 0

    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_gaps_in_ids_are_accepted():
    lines = extract()["lancamentos"]
    for index, line in enumerate(lines):
        line["id"] = 2 * index + 1

    assert len(parse(body(lancamentos=lines)).lancamentos) == 17


def test_section_values():
    for section in ("compras", "internacional", "produtos"):
        lines = extract()["lancamentos"]
        lines[0]["secao"] = section
        parse(body(lancamentos=lines))

    lines = extract()["lancamentos"]
    lines[0]["secao"] = "outros"
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_empty_description_and_date_are_refused():
    lines = extract()["lancamentos"]
    lines[0]["descricao"] = "   "
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))

    lines = extract()["lancamentos"]
    lines[0]["data"] = ""
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_long_description_is_refused():
    lines = extract()["lancamentos"]
    lines[0]["descricao"] = "x" * 300
    parse(body(lancamentos=copy.deepcopy(lines)))

    lines[0]["descricao"] = "x" * 301
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))


def test_three_decimal_places_are_refused():
    lines = extract()["lancamentos"]
    lines[0]["valor"] = 1250.001
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))

    with pytest.raises(ValidationError):
        parse(body(total_lanc_atuais=11906.351))


def test_huge_amount_is_refused():
    lines = extract()["lancamentos"]
    lines[0]["valor"] = 1e12
    with pytest.raises(ValidationError):
        parse(body(lancamentos=lines))

    lines = extract()["lancamentos"]
    lines[0]["valor"] = 999999999999.99
    assert parse(body(lancamentos=lines)).lancamentos[0].valor == Decimal("999999999999.99")


def test_zero_or_501_transactions_are_refused():
    first = extract()["lancamentos"][0]

    with pytest.raises(ValidationError):
        parse(body(lancamentos=[]))

    with pytest.raises(ValidationError):
        parse(body(lancamentos=[{**first, "id": i} for i in range(1, 502)]))

    assert len(parse(body(lancamentos=[{**first, "id": i} for i in range(1, 501)])).lancamentos) == 500


def test_amounts_are_read_as_decimals():
    # Claim 1 of spec section 8: a JSON number is read as its decimal text, not
    # as the binary float, so 0.1 + 0.2 adds to exactly 0.3.
    text = (
        '{"name": "%s", "total_lanc_atuais": 0.3, "lancamentos": ['
        '{"id": 1, "secao": "compras", "data": "05/09", "descricao": "Loja Exemplo", '
        '"valor": 0.1, "categoria": "OUTROS", "duvida": false},'
        '{"id": 2, "secao": "compras", "data": "05/09", "descricao": "Loja Exemplo", '
        '"valor": 0.2, "categoria": "OUTROS", "duvida": false}]}' % NAME
    )

    model = read_payload(text.encode())

    assert [line.valor for line in model.lancamentos] == [Decimal("0.1"), Decimal("0.2")]
    assert lines_total(model.lancamentos) == model.total_lanc_atuais == Decimal("0.3")
