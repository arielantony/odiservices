"""The retry claim against a real Postgres, as app_backend (BE-08, spec 5.2). It is
the only test of the atomic claim: a fake shows that the code asks for a conditional
update, not that the database grants it. Run by make test-db; each test uses a
throwaway database (test_migrations_db.database)."""

import threading
import time
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.db import User, build_engine
from server.retry import claim_retry
from server.settings import Settings
from server.statements import set_status
from server.uploads import store_upload
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_transactions_db import make_user
from tests.access_helpers import AUD, TEAM

pytestmark = pytest.mark.db

UPLOAD_KEY = Fernet.generate_key().decode()  # fictitious
PDF = b"%PDF-1.4\n% fictitious\n%%EOF\n"
NAME = "Fatura Cartão Exemplo, set/2026"
INSERT_FAILED = text(
    "insert into portal.statements (user_id, name, status, failure_code) "
    "values (:u, :n, 'failed', :c) returning id"
)


@pytest.fixture
def engine(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    yield engine
    engine.dispose()


def failed_statement(migrated, user_id, code: str) -> uuid.UUID:
    with owner(migrated).begin() as connection:
        return connection.execute(
            INSERT_FAILED, {"u": user_id, "n": NAME, "c": code}
        ).scalar_one()


def status_of(migrated, statement_id) -> tuple:
    with owner(migrated).connect() as connection:
        return tuple(
            connection.execute(
                text("select status, failure_code from portal.statements where id = :id"),
                {"id": statement_id},
            ).one()
        )


def wait_until_blocked(migrated, timeout: float = 10.0) -> None:
    """Returns once one backend waits on a lock (the second claim, behind the first)."""
    deadline = time.monotonic() + timeout
    with owner(migrated).connect() as connection:
        while time.monotonic() < deadline:
            waiting = connection.execute(
                text(
                    "select count(*) from pg_stat_activity "
                    "where datname = current_database() and wait_event_type = 'Lock'"
                )
            ).scalar_one()
            connection.rollback()
            if waiting:
                return
            time.sleep(0.05)
    raise AssertionError("the second claim never waited on the first")


def test_concurrent_claims_one_wins(engine, migrated):
    # Deterministic, not a race: connection A claims and holds the row's lock. B's
    # claim (another thread) must wait for A. When A commits, B's UPDATE re-checks
    # `status = 'failed'`, matches no row and returns False.
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
    statement_id = failed_statement(migrated, user_id, "extraction_timeout")
    results: dict[str, object] = {}

    holder = Session(engine)
    assert set_status(
        holder, statement_id, "processing", expected="failed", commit=False
    ) is True

    def second_claim() -> None:
        with Session(engine) as session:
            try:
                results["second"] = set_status(
                    session, statement_id, "processing", expected="failed"
                )
            except Exception as exc:  # reported in the main thread
                results["error"] = exc

    thread = threading.Thread(target=second_claim)
    thread.start()
    try:
        wait_until_blocked(migrated)
        holder.commit()
    finally:
        holder.close()
        thread.join(timeout=30)

    assert not thread.is_alive()
    assert "error" not in results, results.get("error")
    assert results["second"] is False
    assert status_of(migrated, statement_id) == ("processing", None)


def test_retry_claim_leaves_other_statements_alone(engine, migrated):
    with owner(migrated).begin() as connection:
        user_id = make_user(connection)
    settings = Settings(
        env="dev",
        access_team_domain=TEAM,
        access_aud=AUD,
        database_url=None,
        upload_encryption_key=SecretStr(UPLOAD_KEY),
    )
    retried = failed_statement(migrated, user_id, "extraction_timeout")
    kept = failed_statement(migrated, user_id, "total_mismatch")
    with Session(engine) as session:
        store_upload(session, retried, PDF, settings=settings)
        session.commit()

    with Session(engine) as session:
        user = session.get(User, user_id)
        assert claim_retry(session, user, retried, settings=settings) == retried

    assert status_of(migrated, retried) == ("processing", None)
    assert status_of(migrated, kept) == ("failed", "total_mismatch")
