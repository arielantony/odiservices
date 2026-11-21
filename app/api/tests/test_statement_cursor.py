"""The limit and cursor helpers of GET /api/statements (BE-06, step 1). Pure
functions: no route, no database."""

import base64
import json
import uuid
from datetime import datetime, timezone

import pytest

from server.statements import (
    DEFAULT_LIMIT,
    REFUSED_INVALID_CURSOR,
    REFUSED_INVALID_LIMIT,
    encode_cursor,
    parse_cursor,
    parse_limit,
)

VALID_ID = str(uuid.UUID(int=99))
MOMENT = "2026-08-04T18:05:00+00:00"


def raw_cursor(body) -> str:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_cursor_round_trip():
    moment = datetime(2026, 8, 4, 18, 5, 0, 123456, tzinfo=timezone.utc)
    statement_id = uuid.UUID(int=7)

    cursor = encode_cursor(moment, statement_id)

    assert "=" not in cursor
    assert parse_cursor(cursor) == (moment, statement_id)


def test_naive_cursor_time_is_refused():
    cursor = raw_cursor({"v": 1, "t": "2026-08-04T18:05:00.123456", "i": VALID_ID})

    with pytest.raises(ValueError):
        parse_cursor(cursor)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!!",
        base64.urlsafe_b64encode(b"[]").rstrip(b"=").decode(),
        raw_cursor({"v": 1, "t": MOMENT}),
        raw_cursor({"v": 1, "t": MOMENT, "i": VALID_ID, "x": 1}),
        raw_cursor({"v": 1, "t": "2026-08-04T18:05:00", "i": VALID_ID}),
        raw_cursor({"v": 1, "t": MOMENT, "i": "not-a-uuid"}),
        raw_cursor({"v": 2, "t": MOMENT, "i": VALID_ID}),
        raw_cursor({"v": True, "t": MOMENT, "i": VALID_ID}),
        "A" * 513,
    ],
)
def test_invalid_cursors_raise_value_error(cursor):
    with pytest.raises(ValueError):
        parse_cursor(cursor)


def test_absent_limit_is_the_default():
    assert parse_limit([]) == DEFAULT_LIMIT == 20


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("20", 20), ("100", 100)])
def test_valid_limits(value, expected):
    assert parse_limit([value]) == expected


@pytest.mark.parametrize(
    "values", [["0"], ["101"], ["-1"], ["1.5"], ["abc"], [""], ["5", "6"], ["0005x"]]
)
def test_invalid_limits_raise_value_error(values):
    with pytest.raises(ValueError):
        parse_limit(values)


def test_refusals_use_the_portal_format():
    assert REFUSED_INVALID_LIMIT[:2] == (422, "invalid_limit")
    assert REFUSED_INVALID_CURSOR == (422, "invalid_cursor", "O cursor da página não é válido.")
