"""The processing status of a statement (BE-07) with no database. The sessions are
the FakeSession of test_statement_read, or one that fails on any use."""

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from server.access import AccessVerifier
from server.db import Statement
from server.main import create_app
from server.settings import Settings
from server.statements import FAILURE_CODES, FAILURE_MESSAGES, STATUSES, set_status
from tests.access_helpers import AUD, TEAM, FakeKeyClient
from test_statement_read import (
    FAKE_USER,
    NAME,
    FakeSession,
    NoDatabase,
    app_with,
    get,
    seeded,
    serving,
)
from fastapi.testclient import TestClient

API = Path(__file__).resolve().parents[1]
MIGRATION = API / "migrations" / "versions" / "0008_statement_status.py"
CREATED_AT = datetime(2026, 11, 10, 14, 3, tzinfo=timezone.utc)


def plain_app():
    return create_app(
        Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
    )


def statement_of(**fields):
    """One statement of FAKE_USER, built in memory with the given state."""
    return Statement(
        id=uuid.uuid4(),
        user_id=FAKE_USER.id,
        name=NAME,
        created_at=CREATED_AT,
        **fields,
    )


def test_status_and_codes_are_fixed():
    assert STATUSES == ("processing", "ready", "failed")
    assert FAILURE_CODES == (
        "invalid_pdf",
        "extraction_unavailable",
        "extraction_timeout",
        "extraction_refused",
        "extraction_truncated",
        "extraction_invalid",
        "unknown_category",
        "total_mismatch",
        "interrupted",
        "upload_not_available",
        "unknown",
    )


def test_every_failure_code_has_a_pt_br_message():
    for code in FAILURE_CODES:
        assert FAILURE_MESSAGES[code], code
    assert FAILURE_MESSAGES["invalid_pdf"] == "PDF ilegível"


def test_migration_vocabulary_matches_code():
    spec = importlib.util.spec_from_file_location("migration_0008", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.STATUSES == STATUSES
    assert migration.FAILURE_CODES == FAILURE_CODES


def test_set_status_refuses_unknown_status():
    with pytest.raises(ValueError) as error:
        set_status(NoDatabase(), uuid.uuid4(), "archived")

    assert "status" in str(error.value)
    assert "archived" not in str(error.value)


def test_set_status_refuses_inconsistent_failure():
    statement_id = uuid.uuid4()
    refusals = [
        ("failed", None),  # a failed statement needs its code
        ("ready", "extraction_timeout"),  # a code only with failed
        ("failed", "stack trace"),  # a code outside the vocabulary
    ]
    for status, code in refusals:
        with pytest.raises(ValueError) as error:
            set_status(NoDatabase(), statement_id, status, code)
        assert "stack trace" not in str(error.value)


def test_get_shows_status_and_failure_message():
    statement = statement_of(
        status="failed", failure_code="invalid_pdf", total_lanc_atuais=None
    )
    client = TestClient(app_with(serving(FakeSession([statement]))))

    response = get(client, statement.id)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["failure_code"] == "invalid_pdf"
    assert data["failure_message"] == "PDF ilegível"
    assert data["transactions"] == []


def test_processing_statement_has_no_total_and_no_lines():
    statement = statement_of(
        status="processing", failure_code=None, total_lanc_atuais=None
    )
    client = TestClient(app_with(serving(FakeSession([statement]))))

    response = get(client, statement.id)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["total"] is None
    assert data["transaction_count"] == 0
    assert data["failure_message"] is None


def test_ready_statement_has_no_failure_message():
    statement_id, session = seeded([(1, "Loja Exemplo", "10.00")])
    client = TestClient(app_with(serving(session)))

    response = get(client, statement_id)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["failure_code"] is None
    assert data["failure_message"] is None


def test_no_route_writes_status():
    # FastAPI 0.162 wraps included routers, so the routes are read from the
    # OpenAPI schema (spec 8, claim 6).
    paths = plain_app().openapi()["paths"]
    pairs = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/statements")
        for method in operations
    }

    assert pairs == {
        ("POST", "/api/statements"),
        ("POST", "/api/statements/upload"),  # BE-03: the upload, a new statement in processing
        ("GET", "/api/statements"),  # BE-06: the list, no status written
        ("GET", "/api/statements/{statement_id}"),
        ("DELETE", "/api/statements/{statement_id}"),  # BE-15: removes the statement, no status
        ("PATCH", "/api/statements/{statement_id}/transactions/{transaction_id}"),
        ("GET", "/api/statements/{statement_id}/summary"),
        ("GET", "/api/statements/{statement_id}/export"),  # BE-14: read-only
        ("POST", "/api/statements/{statement_id}/retry"),  # BE-08: failed -> processing, then extract
    }
