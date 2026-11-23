"""The encrypted upload of a statement PDF against a real Postgres (BE-04). Run by
make test-db. The statement is the canonical fixture, imported through
import_statement (BE-05), and the functions run as app_backend."""

import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from server.db import Statement, StatementUpload, User, build_engine
from server.settings import Settings
from server.uploads import MAX_PDF_BYTES, UploadError, load_upload, store_upload, wipe_upload
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_statement_payload import body
from test_statement_read_db import import_for

pytestmark = pytest.mark.db

PDF = "%PDF-1.4 Fatura Exemplo fictícia".encode()
BIG_PDF = (PDF * (MAX_PDF_BYTES // len(PDF) + 1))[:MAX_PDF_BYTES]


@pytest.fixture
def engine(migrated):
    engine = build_engine(SecretStr(url("app_backend", migrated)))
    yield engine
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(env="dev", upload_encryption_key=Fernet.generate_key().decode())


@pytest.fixture
def statement_id(engine) -> uuid.UUID:
    """A ready statement of a fictitious person, imported as the canonical fixture."""
    with Session(engine) as session:
        user = User(access_subject="sub-uploads", email="uploads@exemplo.com")
        session.add(user)
        session.commit()
        user_id = str(user.id)
    imported = import_for(engine, user_id, body())
    return imported.id


def upload_rows(database, statement_id) -> int:
    with Session(owner(database)) as session:
        return len(
            session.scalars(
                select(StatementUpload).where(StatementUpload.statement_id == statement_id)
            ).all()
        )


def test_store_load_wipe_round_trip(engine, settings, statement_id):
    with Session(engine) as session:
        store_upload(session, statement_id, BIG_PDF, settings=settings)
        session.commit()

    with Session(engine) as session:
        assert load_upload(session, statement_id, settings=settings) == BIG_PDF

    with Session(engine) as session:
        assert wipe_upload(session, statement_id) is True
        session.commit()

    with Session(engine) as session:
        with pytest.raises(UploadError) as error:
            load_upload(session, statement_id, settings=settings)
    assert error.value.code == "upload_missing"


def test_wipe_is_idempotent(engine, settings, statement_id):
    with Session(engine) as session:
        store_upload(session, statement_id, PDF, settings=settings)
        session.commit()
    with Session(engine) as session:
        assert wipe_upload(session, statement_id) is True
        session.commit()
    with Session(engine) as session:
        assert wipe_upload(session, statement_id) is False
        session.commit()


def test_deleting_the_statement_removes_the_upload(database, engine, settings, statement_id):
    with Session(engine) as session:
        store_upload(session, statement_id, PDF, settings=settings)
        session.commit()
    assert upload_rows(database, statement_id) == 1

    with Session(engine) as session:
        session.delete(session.get(Statement, statement_id))
        session.commit()

    assert upload_rows(database, statement_id) == 0


def test_row_is_not_readable_without_the_backend_role(migrated, engine, settings, statement_id):
    # A fresh role has no policy on the table, so RLS hides every row from it.
    # The owner is not used here: a table owner can bypass RLS.
    with Session(engine) as session:
        store_upload(session, statement_id, PDF, settings=settings)
        session.commit()

    with Session(owner(migrated)) as session:
        session.execute(text("CREATE ROLE zz_reader NOLOGIN"))
        session.execute(text("GRANT USAGE ON SCHEMA portal TO zz_reader"))
        session.execute(text("GRANT SELECT ON portal.statement_uploads TO zz_reader"))
        session.commit()
    try:
        with Session(owner(migrated)) as session:
            session.execute(text("SET ROLE zz_reader"))
            count = session.execute(text("SELECT count(*) FROM portal.statement_uploads")).scalar_one()
            session.rollback()
        assert count == 0
    finally:
        with Session(owner(migrated)) as session:
            session.execute(text("DROP OWNED BY zz_reader"))
            session.execute(text("DROP ROLE zz_reader"))
            session.commit()
