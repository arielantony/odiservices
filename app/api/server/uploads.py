"""The encrypted upload of a statement PDF (BE-04).

The PDF is never written to disk. It is kept in `portal.statement_uploads` as a
Fernet token, and only while its statement is not `ready`: the callers (BE-03,
BE-08) decide when to store, keep or wipe it. This module does not look at a
status. Each function takes the caller's session and never commits: the caller
owns the transaction.
"""

from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from server.db import StatementUpload
from server.settings import Settings, get_settings
from server.users import log_event

MAX_PDF_BYTES = 10 * 1024 * 1024  # the "Até 10 MB" of FE-03, shared with BE-03


class UploadError(Exception):
    """A failed upload operation. `code` is one of a fixed set, and str(exc) is
    the code and nothing else: no key, no bytes, no database detail."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def seal_pdf(pdf_bytes: bytes, key: str) -> bytes:
    return Fernet(key).encrypt(pdf_bytes)


def open_pdf(token: bytes, key: str) -> bytes:
    try:
        return Fernet(key).decrypt(token)
    except InvalidToken:
        raise UploadError("upload_unreadable") from None


def _fail(code: str, error: BaseException | None = None) -> UploadError:
    # The code and the class of the cause only, never a message.
    cause = type(error).__name__ if error is not None else "none"
    log_event("WARNING", "upload_failed", code=code, error=cause)
    return UploadError(code)


def _key(settings: Settings | None) -> str:
    settings = settings if settings is not None else get_settings()
    if settings.upload_encryption_key is None:
        raise _fail("upload_key_missing")
    return settings.upload_encryption_key.get_secret_value()


def store_upload(
    session: Session,
    statement_id: UUID,
    pdf_bytes: bytes,
    *,
    settings: Settings | None = None,
) -> None:
    """Seal the PDF and insert its row, flushed but not committed. On a database
    error the caller rolls back, as the transaction is then unusable."""
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise _fail("upload_too_large")
    key = _key(settings)
    token = seal_pdf(pdf_bytes, key)
    try:
        session.add(StatementUpload(statement_id=statement_id, ciphertext=token))
        session.flush()
    except DBAPIError as exc:
        if isinstance(exc, IntegrityError):
            raise _fail("upload_exists", exc) from None
        raise _fail("database_unavailable", exc) from None


def load_upload(
    session: Session,
    statement_id: UUID,
    *,
    settings: Settings | None = None,
) -> bytes:
    """The decrypted PDF of the statement, or an UploadError. Never a partial
    result."""
    key = _key(settings)
    try:
        row = session.get(StatementUpload, statement_id)
    except DBAPIError as exc:
        raise _fail("database_unavailable", exc) from None
    if row is None:
        raise _fail("upload_missing")
    try:
        return open_pdf(row.ciphertext, key)
    except UploadError as exc:
        raise _fail(exc.code) from None


def wipe_upload(session: Session, statement_id: UUID) -> bool:
    """Delete the row. True when one was removed; a second call is False."""
    try:
        result = session.execute(
            delete(StatementUpload).where(StatementUpload.statement_id == statement_id)
        )
    except DBAPIError as exc:
        raise _fail("database_unavailable", exc) from None
    return result.rowcount > 0
