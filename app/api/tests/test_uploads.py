"""The encrypted upload of a statement PDF (BE-04), with no database: the session
is a fake. The PDF is fictitious."""

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError, OperationalError

from server.db import StatementUpload
from server.settings import Settings
from server.uploads import (
    MAX_PDF_BYTES,
    UploadError,
    load_upload,
    open_pdf,
    seal_pdf,
    store_upload,
    wipe_upload,
)

PDF = "%PDF-1.4 Fatura Exemplo fictícia".encode()
WORDS = ("Fatura", "Exemplo", "fictícia")
HOST = "db.exemplo.interno"


class Result:
    def __init__(self, rowcount: int = 0):
        self.rowcount = rowcount


class FakeSession:
    def __init__(
        self,
        *,
        flush_error: Exception | None = None,
        execute_error: Exception | None = None,
        found: object | None = None,
    ):
        self.flush_error = flush_error
        self.execute_error = execute_error
        self.found = found
        self.added: list[object] = []
        self.flushes = 0
        self.commits = 0
        self.touched = False

    def add(self, obj: object) -> None:
        self.touched = True
        self.added.append(obj)

    def flush(self) -> None:
        self.touched = True
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def get(self, model: type, key: object) -> object | None:
        self.touched = True
        if self.execute_error is not None:
            raise self.execute_error
        return self.found

    def execute(self, statement: object) -> Result:
        self.touched = True
        if self.execute_error is not None:
            raise self.execute_error
        return Result(rowcount=1 if self.found is not None else 0)


def settings_with(key: str | None) -> Settings:
    return Settings(
        _env_file=None,
        env="dev",
        upload_encryption_key=key,
    )


@pytest.fixture
def key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def statement_id() -> uuid.UUID:
    return uuid.uuid4()


def operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(f"could not connect to {HOST}"))


def test_seal_and_open_round_trip(key):
    assert open_pdf(seal_pdf(PDF, key), key) == PDF


def test_ciphertext_hides_the_pdf(key):
    token = seal_pdf(PDF, key)

    assert b"%PDF" not in token
    for word in WORDS:
        assert word.encode() not in token


def test_wrong_key_is_unreadable(key):
    token = seal_pdf(PDF, key)

    with pytest.raises(UploadError) as error:
        open_pdf(token, Fernet.generate_key().decode())

    assert error.value.code == "upload_unreadable"


def test_tampered_token_is_unreadable(key):
    token = bytearray(seal_pdf(PDF, key))
    middle = len(token) // 2
    token[middle] = ord("A") if token[middle] != ord("A") else ord("B")

    with pytest.raises(UploadError) as error:
        open_pdf(bytes(token), key)

    assert error.value.code == "upload_unreadable"


def test_too_large_is_refused_before_the_key(statement_id):
    session = FakeSession()

    with pytest.raises(UploadError) as error:
        store_upload(
            session,
            statement_id,
            bytes(MAX_PDF_BYTES + 1),
            settings=settings_with(None),
        )

    assert error.value.code == "upload_too_large"
    assert not session.touched


def test_missing_key_fails_only_when_used(statement_id):
    settings = settings_with(None)
    assert settings.upload_encryption_key is None

    with pytest.raises(UploadError) as stored:
        store_upload(FakeSession(), statement_id, PDF, settings=settings)
    with pytest.raises(UploadError) as loaded:
        load_upload(FakeSession(), statement_id, settings=settings)

    assert stored.value.code == "upload_key_missing"
    assert loaded.value.code == "upload_key_missing"


def test_store_flushes_and_does_not_commit(key, statement_id):
    session = FakeSession()

    store_upload(session, statement_id, PDF, settings=settings_with(key))

    assert len(session.added) == 1
    assert session.flushes == 1
    assert session.commits == 0
    row = session.added[0]
    assert isinstance(row, StatementUpload)
    assert row.statement_id == statement_id
    assert open_pdf(row.ciphertext, key) == PDF


def test_duplicate_store_is_upload_exists(key, statement_id):
    session = FakeSession(
        flush_error=IntegrityError("INSERT", {}, Exception("duplicate key")),
    )

    with pytest.raises(UploadError) as error:
        store_upload(session, statement_id, PDF, settings=settings_with(key))

    assert error.value.code == "upload_exists"


def test_load_without_row_is_upload_missing(key, statement_id):
    with pytest.raises(UploadError) as error:
        load_upload(FakeSession(found=None), statement_id, settings=settings_with(key))

    assert error.value.code == "upload_missing"


def test_database_error_is_database_unavailable(key, statement_id, capsys):
    session = FakeSession(flush_error=operational_error())

    with pytest.raises(UploadError) as error:
        store_upload(session, statement_id, PDF, settings=settings_with(key))

    assert error.value.code == "database_unavailable"
    assert HOST not in str(error.value)
    assert HOST not in capsys.readouterr().out


def test_no_bytes_or_key_in_errors_or_logs(key, statement_id, capsys):
    other = Fernet.generate_key().decode()
    token = seal_pdf(PDF, other)
    stored_row = StatementUpload(statement_id=statement_id, ciphertext=token)
    scenarios = [
        lambda: store_upload(
            FakeSession(), statement_id, bytes(MAX_PDF_BYTES + 1),
            settings=settings_with(key),
        ),
        lambda: store_upload(FakeSession(), statement_id, PDF, settings=settings_with(None)),
        lambda: load_upload(FakeSession(found=stored_row), statement_id, settings=settings_with(key)),
        lambda: load_upload(FakeSession(found=None), statement_id, settings=settings_with(key)),
        lambda: store_upload(
            FakeSession(flush_error=IntegrityError("INSERT", {}, Exception("dup"))),
            statement_id, PDF, settings=settings_with(key),
        ),
        lambda: store_upload(
            FakeSession(flush_error=operational_error()),
            statement_id, PDF, settings=settings_with(key),
        ),
    ]

    for scenario in scenarios:
        with pytest.raises(UploadError) as error:
            scenario()
        assert key not in str(error.value)
        assert other not in str(error.value)
        assert "%PDF" not in str(error.value)

    output = capsys.readouterr().out
    assert key not in output
    assert other not in output
    assert "%PDF" not in output
    assert "Fatura" not in output
    assert "upload_failed" in output
