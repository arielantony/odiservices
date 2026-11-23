"""POST /api/statements/{id}/retry with no database (BE-08, spec 5.1). The session is
a fake from test_statement_read; load_upload, set_status and check_processing_limit
are replaced on server.retry, and run_extraction on the route module, so the real
claim_retry and the real route run. No call leaves the machine."""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

import server.retry as retry
import server.routes.statements as statements_route
from server.access import AccessVerifier
from server.db import Statement
from server.db.session import get_session
from server.main import create_app
from server.routes.uploads import upload_extractor
from server.settings import Settings
from server.statements import FAILURE_MESSAGES, StatementRefused
from server.uploads import UploadError
from server.uploads_limits import REFUSED_TOO_MANY_UPLOADS
from server.users import current_user
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token
from test_statement_read import FAKE_USER, NAME, FakeSession, failing_session, serving

HEADER = "Cf-Access-Jwt-Assertion"
ENCRYPTION_KEY = Fernet.generate_key().decode()  # fictitious
BLOB = b"%PDF-1.4 fictitious blob"
NOT_FOUND = {"error": {"code": "statement_not_found", "message": "A fatura não foi encontrada."}}
NOT_FAILED = {
    "error": {
        "code": "statement_not_failed",
        "message": "Só é possível tentar de novo uma fatura que falhou.",
    }
}
UPLOAD_NOT_AVAILABLE = {
    "error": {
        "code": "upload_not_available",
        "message": "O PDF desta fatura não está mais disponível. Envie a fatura novamente.",
    }
}
DATABASE_UNAVAILABLE = {
    "error": {"code": "database_unavailable", "message": "Não foi possível acessar os dados. Tente novamente."}
}
CREATED_AT = datetime(2026, 11, 10, 14, 3, tzinfo=timezone.utc)
OTHER_USER = SimpleNamespace(id=uuid.UUID("00000000-0000-4000-8000-0000000000b2"))


class ClaimSession(FakeSession):
    """The fake session with the commit and rollback the claim calls."""

    def __init__(self, statements=()):
        super().__init__(statements)
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class FakeClient:
    def extract(self, pdf, categories):  # never called: the job is replaced
        raise AssertionError("the extraction must not run in a route test")


def statement_of(status="failed", user=FAKE_USER, name=NAME):
    return Statement(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        status=status,
        failure_code="extraction_timeout" if status == "failed" else None,
        created_at=CREATED_AT,
    )


@pytest.fixture
def calls(monkeypatch):
    """The fakes of the claim. Each one records its calls and does the default."""
    record = SimpleNamespace(upload=[], status=[], limit=[], background=[], blob=BLOB)

    def load_upload(session, statement_id, **kwargs):
        record.upload.append(statement_id)
        if isinstance(record.blob, Exception):
            raise record.blob
        return record.blob

    def set_status(session, statement_id, status, failure_code=None, *, expected=None, commit=True):
        record.status.append((statement_id, status, failure_code, expected))
        if record.set_status_result is False:
            return False
        for row in session.statements:
            if row.id == statement_id and row.status == expected:
                row.status = status
                row.failure_code = failure_code
                return True
        return False

    def check_processing_limit(session, user, *, settings=None):
        record.limit.append(user.id)
        if record.limit_refusal is not None:
            raise StatementRefused(record.limit_refusal)

    def recording_extraction(engine, statement_id, client, model):
        record.background.append((statement_id, client))

    record.set_status_result = None
    record.limit_refusal = None
    monkeypatch.setattr(retry, "load_upload", load_upload)
    monkeypatch.setattr(retry, "set_status", set_status)
    monkeypatch.setattr(retry, "check_processing_limit", check_processing_limit)
    monkeypatch.setattr(statements_route, "run_extraction", recording_extraction)
    return record


def app_with(session_dependency):
    settings = Settings(
        env="dev",
        access_team_domain=TEAM,
        access_aud=AUD,
        database_url=None,
        anthropic_api_key=SecretStr("chave-ficticia"),
        upload_encryption_key=SecretStr(ENCRYPTION_KEY),
    )
    app = create_app(settings, access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()))
    app.dependency_overrides[current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[upload_extractor] = lambda: FakeClient()
    return app


def post(client, statement_id, token=None):
    return client.post(
        f"/api/statements/{statement_id}/retry", headers={HEADER: token or make_token()}
    )


def session_with(*statements):
    return ClaimSession(list(statements))


def test_retry_requires_access(calls):
    client = TestClient(
        create_app(
            Settings(env="dev", access_team_domain=TEAM, access_aud=AUD, database_url=None),
            access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        )
    )

    response = client.post(f"/api/statements/{uuid.uuid4()}/retry")

    assert response.status_code == 401
    assert calls.upload == calls.status == calls.background == []


def test_malformed_id_is_404(calls):
    client = TestClient(app_with(serving(session_with())))

    for raw in ("abc-123", "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c1", "%20"):
        response = post(client, raw)
        assert response.status_code == 404, raw
        assert response.json() == NOT_FOUND
    assert calls.upload == calls.status == calls.background == []


def test_other_users_statement_is_404(calls):
    other = statement_of(user=OTHER_USER)
    client = TestClient(app_with(serving(session_with(other))))

    foreign = post(client, other.id)
    unknown = post(client, uuid.uuid4())

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == NOT_FOUND
    assert {k: v for k, v in foreign.headers.items() if k != "x-request-id"} == {
        k: v for k, v in unknown.headers.items() if k != "x-request-id"
    }
    assert calls.status == []


def test_ready_statement_is_409_not_failed(calls):
    ready = statement_of(status="ready")
    client = TestClient(app_with(serving(session_with(ready))))

    response = post(client, ready.id)

    assert response.status_code == 409
    assert response.json() == NOT_FAILED
    assert calls.status == []


def test_processing_statement_is_409_not_failed(calls):
    processing = statement_of(status="processing")
    client = TestClient(app_with(serving(session_with(processing))))

    response = post(client, processing.id)

    assert response.status_code == 409
    assert response.json() == NOT_FAILED
    assert calls.status == []


def test_missing_blob_is_409_upload_not_available(calls):
    failed = statement_of()
    calls.blob = UploadError("upload_missing")
    client = TestClient(app_with(serving(session_with(failed))))

    response = post(client, failed.id)

    assert response.status_code == 409
    assert response.json() == UPLOAD_NOT_AVAILABLE
    assert calls.status == []


def test_status_is_checked_before_blob(calls):
    ready = statement_of(status="ready")
    calls.blob = UploadError("upload_missing")
    client = TestClient(app_with(serving(session_with(ready))))

    response = post(client, ready.id)

    assert response.status_code == 409
    assert response.json() == NOT_FAILED
    assert calls.upload == []


def test_retry_puts_failed_statement_back_to_processing(calls):
    failed = statement_of()
    session = session_with(failed)
    client = TestClient(app_with(serving(session)))

    response = post(client, failed.id)

    assert response.status_code == 202
    assert response.json() == {"id": str(failed.id), "status": "processing"}
    assert response.headers["cache-control"] == "no-store"
    assert calls.status == [(failed.id, "processing", None, "failed")]
    assert failed.status == "processing"
    assert failed.failure_code is None
    assert session.commits == 1
    # The background job ran after the response was built, with the statement id.
    assert [(sid, type(client)) for sid, client in calls.background] == [(failed.id, FakeClient)]


def test_claim_lost_to_a_concurrent_retry_is_409(calls):
    failed = statement_of()
    session = session_with(failed)
    calls.set_status_result = False
    failed.status = "processing"  # the winner of the race has already claimed it
    client = TestClient(app_with(serving(session)))

    response = post(client, failed.id)

    assert response.status_code == 409
    assert response.json() == NOT_FAILED
    assert calls.background == []


def test_claim_lost_to_a_delete_is_404(calls):
    failed = statement_of()
    session = session_with(failed)
    calls.set_status_result = False
    session.statements.clear()  # deleted between the read and the claim
    client = TestClient(app_with(serving(session)))

    response = post(client, failed.id)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert calls.background == []


def test_processing_limit_refusal_is_passed_through(calls):
    failed = statement_of()
    session = session_with(failed)
    calls.limit_refusal = REFUSED_TOO_MANY_UPLOADS
    client = TestClient(app_with(serving(session)))

    response = post(client, failed.id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_uploads"
    assert calls.status == []
    assert calls.background == []


def test_retry_logs_carry_no_values(calls, capsys):
    failed = statement_of(name="Fatura Teste.pdf")  # failed with extraction_timeout
    client = TestClient(app_with(serving(session_with(failed))))

    response = post(client, failed.id)
    output = capsys.readouterr().out

    assert response.status_code == 202
    events = [json.loads(line) for line in output.splitlines() if line]
    (request,) = [event for event in events if event["event"] == "request"]
    assert request["route"] == "/api/statements/{statement_id}/retry"
    assert str(failed.id) not in json.dumps(request)
    (started,) = [event for event in events if event["event"] == "statement_retry_started"]
    assert started["statement_id"] == str(failed.id)
    assert started["user_id"] == str(FAKE_USER.id)
    assert set(started) == {"ts", "level", "event", "statement_id", "user_id"}
    assert "Fatura Teste.pdf" not in output
    assert FAILURE_MESSAGES["extraction_timeout"] not in output


def test_database_error_is_503_without_details(calls, capsys):
    client = TestClient(app_with(failing_session))

    response = post(client, uuid.uuid4())
    output = capsys.readouterr().out

    assert response.status_code == 503
    assert response.json() == DATABASE_UNAVAILABLE
    assert "127.0.0.1" not in response.text
    assert "127.0.0.1" not in output
    events = [json.loads(line) for line in output.splitlines() if line]
    (failure,) = [event for event in events if event["event"] == "database_error"]
    assert failure["error"] == "OperationalError"
    assert calls.status == []
