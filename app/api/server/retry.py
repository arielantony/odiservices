"""Retry a failed extraction (BE-08, spec 3.3). The claim is one conditional update
through set_status(expected='failed'): of two concurrent retries, only one matches
the row. The extraction itself runs in the background job of BE-03 (run_extraction),
which the route adds; this module never runs it."""

from uuid import UUID

from sqlalchemy.orm import Session

from server.access import AccessError
from server.db import User
from server.db.session import DATABASE_UNAVAILABLE
from server.settings import Settings
from server.statements import REFUSED_NOT_FOUND, StatementRefused, owned_statement, set_status
from server.uploads import UploadError, load_upload
from server.uploads_limits import check_processing_limit

REFUSED_NOT_FAILED = (
    409,
    "statement_not_failed",
    "Só é possível tentar de novo uma fatura que falhou.",
)
REFUSED_UPLOAD_NOT_AVAILABLE = (
    409,
    "upload_not_available",
    "O PDF desta fatura não está mais disponível. Envie a fatura novamente.",
)


def claim_retry(
    session: Session,
    user: User,
    statement_id: UUID,
    *,
    settings: Settings | None = None,
) -> UUID:
    """Move a failed statement of `user` back to `processing` and return its id.
    Raises StatementRefused with the spec's 404, 409 or the limit's 429. Plain def:
    the route runs it in the threadpool. The request's session holds the lock of
    the processing limit until the commit below."""
    statement = owned_statement(session, user, statement_id)
    if statement is None:
        raise StatementRefused(REFUSED_NOT_FOUND)
    if statement.status != "failed":
        raise StatementRefused(REFUSED_NOT_FAILED)
    try:
        # The real load_upload decrypts the blob; the bytes are dropped here. The
        # job of BE-03 loads it again to extract.
        load_upload(session, statement_id, settings=settings)
    except UploadError as exc:
        if exc.code == "database_unavailable":
            raise AccessError(*DATABASE_UNAVAILABLE) from None
        session.rollback()
        raise StatementRefused(REFUSED_UPLOAD_NOT_AVAILABLE) from None

    check_processing_limit(session, user, settings=settings)

    if not set_status(
        session, statement_id, "processing", expected="failed", commit=False
    ):
        # Lost to a concurrent retry (the row reads processing) or deleted: the
        # re-read tells the two apart. The stale object is fine: only existence is read.
        if owned_statement(session, user, statement_id) is None:
            raise StatementRefused(REFUSED_NOT_FOUND)
        raise StatementRefused(REFUSED_NOT_FAILED)
    session.commit()
    return statement_id
