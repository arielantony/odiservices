"""Resolve the Access identity to a `portal.users` row (BE-24).

The row is found by the Access `sub` and created the first time the person is
seen. The email is stored once and never updated: when the token carries
another one, the event is flagged in the log and the stored row is served.
The email, the subject and the token are never logged.
"""

import json
import sys
from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from server.access import UNAUTHORIZED, AccessError, AccessIdentity, require_access
from server.db.models import User
from server.db.session import DATABASE_UNAVAILABLE, get_session

NOT_ALLOWED = (
    403,
    "user_not_allowed",
    "Seu acesso não pode ser identificado. Fale com o administrador.",
)
CONFLICT = (
    409,
    "user_conflict",
    "Já existe um cadastro com este e-mail. Fale com o administrador.",
)
EMAIL_CONSTRAINT = "uq_users_email"


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower() or None


def log_event(level: str, event: str, **ids: str) -> None:
    """One JSON line on stdout. Ids only, never an email or a subject."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "event": event,
        **ids,
    }
    sys.stdout.write(json.dumps(entry) + "\n")
    sys.stdout.flush()


def find_by_subject(session: Session, subject: str) -> User | None:
    return session.scalars(select(User).where(User.access_subject == subject)).one_or_none()


def create_user(session: Session, subject: str, email: str) -> tuple[User, bool]:
    """Insert the row and read it back. Returns the row and whether this call
    made it: a row made meanwhile by the same person (two first requests
    together) is read, not duplicated."""
    try:
        inserted = session.execute(
            insert(User)
            .values(access_subject=subject, email=email)
            .on_conflict_do_nothing(index_elements=["access_subject"])
            .returning(User.id)
        ).scalar_one_or_none()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig.diag, "constraint_name", None) == EMAIL_CONSTRAINT:
            log_event("WARNING", "user_email_conflict")
            raise AccessError(*CONFLICT) from None
        raise
    user = find_by_subject(session, subject)
    assert user is not None
    return user, inserted is not None


def resolve(session: Session, identity: AccessIdentity) -> User:
    email = normalize_email(identity.email)
    user = find_by_subject(session, identity.subject)
    if user is not None:
        if email is not None and email != user.email:
            log_event("WARNING", "user_email_mismatch", user_id=str(user.id))
        return user
    if email is None:
        raise AccessError(*NOT_ALLOWED)
    user, created = create_user(session, identity.subject, email)
    if created:
        log_event("INFO", "user_created", user_id=str(user.id))
    return user


def current_user(
    identity: AccessIdentity | None = Depends(require_access),
    session: Session = Depends(get_session),
) -> User:
    """The person behind the verified token. Depends on `require_access`,
    which FastAPI runs once per request."""
    if identity is None:
        raise AccessError(*UNAUTHORIZED)
    try:
        return resolve(session, identity)
    except DBAPIError as exc:
        if isinstance(exc, IntegrityError):
            raise
        # The class name only: a driver message can hold the host.
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
