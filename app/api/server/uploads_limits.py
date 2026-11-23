"""The limit of statements in `processing` per person (BE-03, spec 3.5). BE-08
calls the same check before a retry. The count is taken under a transaction-
scoped advisory lock on the person, so two uploads of one person cannot both
pass it. Before the count, the statements of the person that have been
`processing` for longer than 15 minutes are marked `failed` with `interrupted`:
that covers a process that stopped during an extraction (no startup job)."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from server.db import Statement, User
from server.settings import Settings, get_settings
from server.statements import StatementRefused

STALE_AFTER = timedelta(minutes=15)
REFUSED_TOO_MANY_UPLOADS = (
    429,
    "too_many_uploads",
    "Há faturas sendo classificadas. Aguarde antes de enviar outra.",
)


def user_lock_key(user_id: UUID):
    """The advisory lock key of a person: a 64-bit hash of the id's text. Shared
    by the check and by the tests that hold the lock."""
    return func.hashtextextended(str(user_id), 0)


def check_processing_limit(session: Session, user: User, *, settings: Settings | None = None) -> None:
    """Raise the 429 when the person already has the maximum of `processing`
    statements. Takes the person's lock and marks the stale statements first. The
    lock lasts until the caller's commit, so the caller must insert before it
    commits. On a refusal the sweep is committed before the error is raised."""
    settings = settings if settings is not None else get_settings()
    session.execute(select(func.pg_advisory_xact_lock(user_lock_key(user.id))))
    session.execute(
        update(Statement)
        .where(
            Statement.user_id == user.id,
            Statement.status == "processing",
            Statement.created_at < func.now() - STALE_AFTER,
        )
        .values(status="failed", failure_code="interrupted", updated_at=func.now())
    )
    processing = session.scalar(
        select(func.count())
        .select_from(Statement)
        .where(Statement.user_id == user.id, Statement.status == "processing")
    )
    if processing >= settings.max_processing_statements:
        session.commit()
        raise StatementRefused(REFUSED_TOO_MANY_UPLOADS)
