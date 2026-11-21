"""GET /api/categories: the categories and their labels, in their fixed order
(BE-16). Read-only, the same answer for every signed-in person."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.access import AccessError
from server.categories import list_categories
from server.db import User
from server.db.session import DATABASE_UNAVAILABLE, get_session
from server.users import current_user, log_event

router = APIRouter()


@router.get("/api/categories")
async def get_categories(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    try:
        views = await run_in_threadpool(list_categories, session)
    except DBAPIError as exc:
        if isinstance(exc, IntegrityError):
            raise
        # The class name only: a driver message can hold the host.
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    return JSONResponse(
        [view.model_dump() for view in views],
        headers={"Cache-Control": "no-store"},
    )
