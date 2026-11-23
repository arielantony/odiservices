"""POST /api/statements/upload against a real Postgres, as app_backend (BE-03, spec
5.3). The extraction client is a fake that returns the canonical fixture (or a
changed one); the background job is the real run_extraction. Run by make test-db."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text

from server.access import AccessVerifier
from server.db import build_engine
from server.main import create_app
from server.routes.uploads import upload_extractor
from server.settings import Settings, get_settings
from server.uploads_limits import user_lock_key
from tests.access_helpers import AUD, EMAIL, TEAM, FakeKeyClient, make_token
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_uploads_route import FILE_NAME, MULTIPART, multipart, pdf

pytestmark = pytest.mark.db

HEADER = "Cf-Access-Jwt-Assertion"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "statement-example-2026-09.json"
UPLOAD_KEY = Fernet.generate_key().decode()
PDF = pdf()


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def mismatched_text() -> str:
    """The fixture with its total one cent higher (rule 9 fails)."""
    data = json.loads(fixture_text(), parse_float=Decimal)
    data["total_lanc_atuais"] = float(data["total_lanc_atuais"] + Decimal("0.01"))
    return json.dumps(data, default=float)


class DbClient:
    """The fake extraction client: it returns `answer` and records the calls."""

    def __init__(self, answer: str):
        self.answer = answer
        self.calls = 0

    def extract(self, pdf: bytes, categories: list[str]) -> str:
        self.calls += 1
        return self.answer


@pytest.fixture(autouse=True)
def upload_key_env(monkeypatch):
    # The background job loads the blob with the global settings (BE-04's default),
    # as it does in production, where both come from the same environment.
    monkeypatch.setenv("PORTAL_UPLOAD_ENCRYPTION_KEY", UPLOAD_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    yield engine
    engine.dispose()


def make_client(engine, answer: str) -> tuple[TestClient, DbClient]:
    settings = Settings(
        env="dev",
        access_team_domain=TEAM,
        access_aud=AUD,
        anthropic_api_key=SecretStr("chave-ficticia"),
        upload_encryption_key=SecretStr(UPLOAD_KEY),
        max_processing_statements=2,
    )
    client = DbClient(answer)
    app = create_app(
        settings,
        access_verifier=AccessVerifier(TEAM, AUD, FakeKeyClient()),
        engine=engine,
    )
    app.dependency_overrides[upload_extractor] = lambda: client
    return TestClient(app), client


def upload(client: TestClient, data: bytes = PDF):
    body = multipart(("file", "application/pdf", FILE_NAME, data))
    return client.post(
        "/api/statements/upload",
        content=body,
        headers={HEADER: make_token(), "Content-Type": MULTIPART},
    )


def add_user(migrated, subject: str, email: str) -> uuid.UUID:
    with owner(migrated).begin() as connection:
        return connection.execute(
            text(
                "insert into portal.users (access_subject, email) "
                "values (:subject, :email) returning id"
            ),
            {"subject": subject, "email": email},
        ).scalar_one()


def add_statement(
    migrated,
    user_id: uuid.UUID,
    status: str,
    age: timedelta,
    updated_age: timedelta | None = None,
) -> None:
    with owner(migrated).begin() as connection:
        connection.execute(
            text(
                "insert into portal.statements "
                "(user_id, name, status, created_at, updated_at) "
                "values (:user, 'Fatura de teste', :status, now() - :age, now() - :updated)"
            ),
            {
                "user": user_id,
                "status": status,
                "age": age,
                "updated": age if updated_age is None else updated_age,
            },
        )


def statement_rows(migrated) -> list:
    with owner(migrated).connect() as connection:
        return connection.execute(
            text(
                "select status, failure_code, total_lanc_atuais, "
                "(select count(*) from portal.transactions t where t.statement_id = s.id) "
                "from portal.statements s order by created_at"
            )
        ).all()


def blob_count(migrated) -> int:
    with owner(migrated).connect() as connection:
        return connection.execute(text("select count(*) from portal.statement_uploads")).scalar_one()


def test_upload_creates_processing_row_and_blob(engine, migrated):
    client, fake = make_client(engine, fixture_text())

    response = upload(client)

    assert response.status_code == 202
    assert fake.calls == 1
    [row] = statement_rows(migrated)
    assert row.status == "ready"
    assert row.failure_code is None
    assert row[3] == 17
    assert blob_count(migrated) == 0


def test_failed_extraction_keeps_blob_and_retry_data(engine, migrated):
    # A total one cent off the sum: rule 9 refuses it; the blob stays for a retry.
    client, _ = make_client(engine, mismatched_text())

    response = upload(client)

    assert response.status_code == 202
    [row] = statement_rows(migrated)
    assert row.status == "failed"
    assert row.failure_code == "total_mismatch"
    assert row[3] == 0
    assert blob_count(migrated) == 1


def test_stale_processing_is_interrupted(engine, migrated):
    user_id = add_user(migrated, "sub-fulano", EMAIL)
    add_statement(migrated, user_id, "processing", timedelta(minutes=20))
    client, _ = make_client(engine, fixture_text())

    response = upload(client)

    assert response.status_code == 202
    rows = statement_rows(migrated)
    assert rows[0].status == "failed"
    assert rows[0].failure_code == "interrupted"


def test_recently_retried_statement_is_not_swept(engine, migrated):
    # A retry bumps updated_at, not created_at: the sweep must go by updated_at.
    user_id = add_user(migrated, "sub-retry", "retry@exemplo.com")
    add_statement(
        migrated, user_id, "processing", timedelta(hours=2), updated_age=timedelta(minutes=1)
    )
    client, _ = make_client(engine, fixture_text())

    response = upload(client)

    assert response.status_code == 202
    assert statement_rows(migrated)[0].status == "processing"


def test_lock_serialises_the_count(engine, migrated):
    # Connection A holds the person's lock, as an upload does until its commit.
    # Connection B, with the same key, must not get it; after A commits it must.
    user_id = add_user(migrated, "sub-lock", "trava@exemplo.com")
    key = user_lock_key(user_id)
    lock = select(func.pg_try_advisory_xact_lock(key))

    with engine.connect() as held, engine.connect() as other:
        transaction = held.begin()
        held.execute(select(func.pg_advisory_xact_lock(key)))
        assert other.execute(lock).scalar_one() is False
        other.rollback()
        transaction.commit()
        assert other.execute(lock).scalar_one() is True
        other.rollback()


def test_other_users_processing_is_not_counted(engine, migrated):
    other = add_user(migrated, "sub-beltrano", "beltrano@exemplo.com")
    add_statement(migrated, other, "processing", timedelta(minutes=1))
    add_statement(migrated, other, "processing", timedelta(minutes=1))
    client, fake = make_client(engine, fixture_text())

    response = upload(client)

    assert response.status_code == 202
    assert fake.calls == 1


def test_app_role_can_run_the_flow(engine, migrated):
    with engine.connect() as connection:
        assert connection.execute(text("select current_user")).scalar_one() == "app_backend"
    client, fake = make_client(engine, fixture_text())

    response = upload(client)

    assert response.status_code == 202
    assert [row.status for row in statement_rows(migrated)] == ["ready"]
    assert fake.calls == 1
