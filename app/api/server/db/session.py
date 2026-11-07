"""The request-scoped database session (BE-24)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from server.access import AccessError

DATABASE_UNAVAILABLE = (
    503,
    "database_unavailable",
    "Não foi possível acessar os dados. Tente novamente.",
)


def get_session(request: Request) -> Iterator[Session]:
    """One session per request, closed after it. With no engine (no
    `PORTAL_DATABASE_URL`) the request is refused with a 503."""
    engine = request.app.state.engine
    if engine is None:
        raise AccessError(*DATABASE_UNAVAILABLE)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
