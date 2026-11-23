"""POST /api/statements/upload against a fake session, with no database and no
network (BE-03, spec 5.2). The Access check is real; the person, the session,
the extraction client and the background job are fakes. The PDFs are fictitious
byte strings built in the test."""

import json
import re
import tempfile
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import server.routes.uploads as uploads
from server.access import AccessVerifier
from server.db import Statement
from server.db.models import StatementUpload
from server.db.session import get_session
from server.main import create_app
from server.routes.uploads import upload_extractor
from server.settings import Settings
from server.users import current_user
from tests.access_helpers import AUD, TEAM, FakeKeyClient, make_token

HEADER = "Cf-Access-Jwt-Assertion"
UPLOAD_KEY = "eiGvYS3oWh0ZrGnAkfQwDK5jMC3IdXPJhzQYLkYTWac="  # fictitious Fernet key
BOUNDARY = "fronteira-ficticia"
FILE_NAME = "Fatura Exemplo Secreta.pdf"
PDF_TEXT = b"TEXTO-FICTICIO-DA-FATURA"
PERSON = SimpleNamespace(id=uuid.UUID("00000000-0000-4000-8000-0000000000b1"))
NAME_PATTERN = re.compile(r"^Fatura enviada em \d{2}/\d{2}/\d{4}$")
ALLOWED_LOG_KEYS = {"ts", "level", "event", "statement_id", "code"}


def pdf(payload: bytes = b"", head: bytes = b"%PDF-1.4\n") -> bytes:
    return head + PDF_TEXT + payload + b"\n%%EOF\n"


def multipart(*parts: tuple[str, str, str, bytes], filename: str = FILE_NAME) -> bytes:
    """Each part is (field name, Content-Type, file name or '', data)."""
    body = b""
    for name, ctype, part_file, data in parts:
        disposition = f'form-data; name="{name}"'
        if part_file:
            disposition += f'; filename="{part_file}"'
        body += (
            f"--{BOUNDARY}\r\nContent-Disposition: {disposition}\r\n"
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + data + b"\r\n"
    return body + f"--{BOUNDARY}--\r\n".encode()


def upload_body(data: bytes, ctype: str = "application/pdf", name: str = "file") -> bytes:
    return multipart((name, ctype, FILE_NAME, data))


MULTIPART = f"multipart/form-data; boundary={BOUNDARY}"


class FakeSession:
    """The writes of the route: rows are kept on commit only, so a refusal that
    did not commit leaves no row. `processing` is the count the limit reads."""

    def __init__(self, processing: int = 0):
        self.processing = processing
        self.pending: list = []
        self.committed: list = []
        self.commits = 0

    def execute(self, statement):
        return SimpleNamespace(rowcount=0)

    def scalar(self, statement):
        return self.processing

    def add(self, obj):
        self.pending.append(obj)

    def flush(self):
        for obj in self.pending:
            if isinstance(obj, Statement) and obj.id is None:
                obj.id = uuid.uuid4()

    def commit(self):
        self.committed += self.pending
        self.pending = []
        self.commits += 1

    def rollback(self):
        self.pending = []

    def statements(self) -> list:
        return [obj for obj in self.committed if isinstance(obj, Statement)]


class FakeClient:
    """The extraction client. The background job is replaced, so it is never called."""

    def extract(self, pdf: bytes, categories: list[str]) -> str:
        raise AssertionError("no extraction in a route test")


@pytest.fixture
def jobs(monkeypatch) -> list:
    calls: list = []

    def recorder(engine, statement_id, client, model):
        calls.append(statement_id)

    monkeypatch.setattr(uploads, "run_extraction", recorder)
    return calls


def make_client(session: FakeSession, *, anthropic: bool = True, upload_key: bool = True,
                override_client: bool = True) -> TestClient:
    settings = Settings(
        env="dev",
        access_team_domain=TEAM,
        access_aud=AUD,
        anthropic_api_key=SecretStr("chave-ficticia") if anthropic else None,
        upload_encryption_key=SecretStr(UPLOAD_KEY) if upload_key else None,
        statement_max_bytes=10 * 1024 * 1024,
        max_processing_statements=2,
    )
    app = create_app(settings, access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()))
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[current_user] = lambda: PERSON
    if override_client:
        app.dependency_overrides[upload_extractor] = lambda: FakeClient()
    return TestClient(app)


def post(client: TestClient, body, ctype: str = MULTIPART, **headers):
    return client.post(
        "/api/statements/upload",
        content=body,
        headers={HEADER: make_token(), "Content-Type": ctype, **headers},
    )


def log_lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_requires_access():
    session = FakeSession()
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD,
                        anthropic_api_key=SecretStr("chave-ficticia"),
                        upload_encryption_key=SecretStr(UPLOAD_KEY))
    app = create_app(settings, access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()))
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    response = client.post("/api/statements/upload", content=upload_body(pdf()),
                           headers={"Content-Type": MULTIPART})

    assert response.status_code == 401
    assert session.committed == [] and session.pending == []


def test_no_key_is_503_and_no_row(jobs):
    session = FakeSession()
    client = make_client(session, anthropic=False, override_client=False)

    response = post(client, upload_body(pdf()))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "extraction_unavailable"
    assert session.committed == [] and session.commits == 0
    assert jobs == []


def test_no_upload_key_is_503_and_no_row(jobs):
    session = FakeSession()
    client = make_client(session, upload_key=False)

    response = post(client, upload_body(pdf()))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "extraction_unavailable"
    assert session.committed == [] and session.commits == 0
    assert jobs == []


def test_oversized_content_length_is_413(jobs):
    session = FakeSession()
    client = make_client(session)
    too_big = 10 * 1024 * 1024 + 64 * 1024 + 1

    response = post(client, upload_body(pdf()), **{"Content-Length": str(too_big)})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert session.committed == []


def test_oversized_chunked_body_is_413(jobs):
    session = FakeSession()
    client = make_client(session)
    chunk = b"0" * 65536
    chunks = (chunk for _ in range((10 * 1024 * 1024 + 64 * 1024) // 65536 + 2))

    response = post(client, chunks)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert session.committed == []


def test_part_over_the_limit_is_413(jobs):
    session = FakeSession()
    settings_client = make_client(session)
    app = settings_client.app
    app.state.settings.statement_max_bytes = 1000

    response = post(settings_client, upload_body(pdf(b"0" * 2000)))

    assert response.status_code == 413
    assert session.committed == []


@pytest.mark.parametrize(
    "body",
    [
        f"--{BOUNDARY}--\r\n".encode(),  # zero parts
        multipart(("file", "application/pdf", FILE_NAME, pdf()),
                  ("file", "application/pdf", FILE_NAME, pdf())),  # two file parts
        upload_body(pdf(), name="other"),  # a part with another name
    ],
    ids=["no_part", "two_files", "other_name"],
)
def test_two_files_or_no_file_is_422(body, jobs):
    session = FakeSession()
    client = make_client(session)

    response = post(client, body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upload"
    assert session.committed == []


def test_wrong_type_is_415(jobs):
    session = FakeSession()
    client = make_client(session)

    as_text = post(client, upload_body(pdf(), ctype="text/plain"))
    not_pdf = post(client, upload_body(b"texto qualquer, sem cabecalho"))

    assert as_text.status_code == 415
    assert not_pdf.status_code == 415
    assert as_text.json()["error"]["code"] == "unsupported_file_type"
    assert not_pdf.json()["error"]["code"] == "unsupported_file_type"
    assert session.committed == []


def test_encrypted_pdf_is_422(jobs):
    session = FakeSession()
    client = make_client(session)

    response = post(client, upload_body(pdf(b"\n/Encrypt 7 0 R\n")))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pdf_encrypted"
    assert session.committed == []


def test_too_many_processing_is_429(jobs):
    session = FakeSession(processing=2)
    client = make_client(session)

    response = post(client, upload_body(pdf()))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_uploads"
    assert session.statements() == []
    assert not any(isinstance(obj, StatementUpload) for obj in session.committed)
    assert jobs == []


def test_accepted_upload_is_202(jobs):
    session = FakeSession()
    client = make_client(session)
    data = pdf()

    response = post(client, upload_body(data))

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"id", "status"}
    assert body["status"] == "processing"
    assert response.headers["cache-control"] == "no-store"
    [statement] = session.statements()
    assert str(statement.id) == body["id"]
    assert statement.status == "processing"
    assert statement.user_id == PERSON.id
    assert NAME_PATTERN.match(statement.name)
    [blob] = [obj for obj in session.committed if isinstance(obj, StatementUpload)]
    assert blob.statement_id == statement.id
    assert data not in blob.ciphertext and PDF_TEXT not in blob.ciphertext
    assert jobs == [statement.id]


def test_upload_does_not_spool_to_disk(jobs, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the upload was written to a temporary file")

    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile"):
        monkeypatch.setattr(tempfile, name, forbidden)
    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", forbidden, raising=False)
    session = FakeSession()
    client = make_client(session)
    big = pdf(b"0" * (2 * 1024 * 1024))

    response = post(client, upload_body(big))

    assert response.status_code == 202
    assert len(jobs) == 1


def test_error_bodies_carry_no_file_name_or_bytes(jobs, capsys):
    session = FakeSession()
    client = make_client(session)

    refusals = [
        post(client, upload_body(pdf(b"\n/Encrypt 7 0 R\n"))),
        post(client, upload_body(pdf(), ctype="text/plain")),
    ]

    for response in refusals:
        assert FILE_NAME not in response.text
        assert PDF_TEXT.decode() not in response.text
    output = capsys.readouterr().out
    assert FILE_NAME not in output
    assert PDF_TEXT.decode() not in output


def test_upload_logs_carry_no_values(jobs, capsys):
    session = FakeSession()
    client = make_client(session)

    post(client, upload_body(pdf(b"\n/Encrypt 7 0 R\n")))
    post(client, upload_body(pdf()))
    lines = log_lines(capsys)

    upload_events = [line for line in lines if line["event"].startswith("statement_upload")]
    assert {line["event"] for line in upload_events} == {
        "statement_upload_refused", "statement_upload_accepted"
    }
    for line in upload_events:
        assert set(line) <= ALLOWED_LOG_KEYS
    assert PDF_TEXT.decode() not in json.dumps(lines)
    assert FILE_NAME not in json.dumps(lines)
