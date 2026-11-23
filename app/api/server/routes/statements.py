"""POST /api/statements: store a card statement for the person in the token
(BE-05). The body is read by hand, so the size is checked before anything is
parsed, and a body that fails its model reaches the handler in main.py."""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.access import AccessError
from server.db import User
from server.db.session import DATABASE_UNAVAILABLE, get_session
from server.statements import (
    MAX_BODY_BYTES,
    MAX_PATCH_BYTES,
    REFUSED_INVALID,
    REFUSED_INVALID_CURSOR,
    REFUSED_INVALID_LIMIT,
    REFUSED_NOT_FOUND,
    REFUSED_TOO_LARGE,
    REFUSED_TRANSACTION_NOT_FOUND,
    StatementRefused,
    import_statement,
    owned_statement,
    parse_cursor,
    parse_limit,
    read_category_summary,
    read_patch,
    read_payload,
    read_statement_page,
    read_statement,
    refusal_response,
    update_transaction,
)
from server.users import current_user, log_event

router = APIRouter()


@router.post("/api/statements", status_code=201)
async def create_statement(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        return refusal_response(REFUSED_INVALID)
    if declared > MAX_BODY_BYTES:
        return refusal_response(REFUSED_TOO_LARGE)
    body = await request.body()
    # Without a Content-Length (a chunked body) the read above is not bounded;
    # this refuses the body once it is read (spec 8, claim 3).
    if len(body) > MAX_BODY_BYTES:
        return refusal_response(REFUSED_TOO_LARGE)

    try:
        payload = read_payload(body)
    except ValidationError as exc:
        # The input is left out: the handler answers the portal's format.
        raise RequestValidationError(
            exc.errors(include_url=False, include_context=False, include_input=False)
        ) from None
    except ValueError:
        raise RequestValidationError(
            [{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON"}]
        ) from None

    try:
        result = await run_in_threadpool(import_statement, session, user, payload)
    except StatementRefused as exc:
        return refusal_response(exc.refusal)
    except DBAPIError as exc:
        if isinstance(exc, IntegrityError):
            raise
        # The class name only: a driver message can hold the host.
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    return JSONResponse(
        {
            "id": str(result.id),
            "name": result.name,
            "total": f"{result.total:.2f}",
            "transaction_count": result.transaction_count,
            "doubtful_count": result.doubtful_count,
        },
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/statements")
async def list_statements(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """One page of the person's statements, newest first (BE-06). The query is
    read by hand, so a bad limit or cursor is invalid_limit or invalid_cursor, not
    the 422 of main.py. The limit is checked before the cursor, and neither reaches
    the database when it is refused."""
    try:
        limit = parse_limit(request.query_params.getlist("limit"))
    except ValueError:
        return refusal_response(REFUSED_INVALID_LIMIT)
    cursors = request.query_params.getlist("cursor")
    after = None
    if cursors:
        if len(cursors) != 1:
            return refusal_response(REFUSED_INVALID_CURSOR)
        try:
            after = parse_cursor(cursors[0])
        except ValueError:
            return refusal_response(REFUSED_INVALID_CURSOR)
    try:
        view = await run_in_threadpool(read_statement_page, session, user, limit, after)
    except DBAPIError as exc:
        # The class name only: a driver message can hold the host.
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    return JSONResponse(view.model_dump(), headers={"Cache-Control": "no-store"})


@router.get("/api/statements/{statement_id}")
async def get_statement(
    statement_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    # Read as a string and parsed here, so a malformed id is the same 404 as an
    # unknown one, not the 422 of BE-05 (spec 3.1).
    try:
        parsed = uuid.UUID(statement_id)
    except ValueError:
        return refusal_response(REFUSED_NOT_FOUND)
    try:
        view = await run_in_threadpool(read_statement, session, user, parsed)
    except DBAPIError as exc:
        # The class name only: a driver message can hold the host (spec 3.4).
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    if view is None:
        return refusal_response(REFUSED_NOT_FOUND)
    return JSONResponse(view.model_dump(), headers={"Cache-Control": "no-store"})


@router.patch("/api/statements/{statement_id}/transactions/{transaction_id}")
async def patch_transaction(
    statement_id: str,
    transaction_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Set the category and/or the reviewed flag of one line (BE-11). The order of
    the checks is the spec's (3.1): the statement is confirmed as the person's
    before the body is read, so a foreign and a missing id answer alike."""
    # Both ids are strings and parsed here, so a malformed one is a 404, not a 422.
    try:
        parsed = uuid.UUID(statement_id)
    except ValueError:
        return refusal_response(REFUSED_NOT_FOUND)
    try:
        if await run_in_threadpool(owned_statement, session, user, parsed) is None:
            return refusal_response(REFUSED_NOT_FOUND)

        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            return refusal_response(REFUSED_INVALID)
        if declared > MAX_PATCH_BYTES:
            return refusal_response(REFUSED_TOO_LARGE)
        body = await request.body()
        # Without a Content-Length the read above is not bounded; refuse it here.
        if len(body) > MAX_PATCH_BYTES:
            return refusal_response(REFUSED_TOO_LARGE)
        try:
            patch = read_patch(body)
        except ValidationError as exc:
            # The input is left out: the handler answers the portal's format.
            raise RequestValidationError(
                exc.errors(include_url=False, include_context=False, include_input=False)
            ) from None
        except ValueError:
            raise RequestValidationError(
                [{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON"}]
            ) from None

        try:
            line_id = uuid.UUID(transaction_id)
        except ValueError:
            return refusal_response(REFUSED_TRANSACTION_NOT_FOUND)
        item = await run_in_threadpool(
            update_transaction, session, user, parsed, line_id, patch
        )
    except StatementRefused as exc:
        return refusal_response(exc.refusal)
    except DBAPIError as exc:
        if isinstance(exc, IntegrityError):
            raise
        # The class name only: a driver message can hold the host (spec 3.4).
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    return JSONResponse(item.model_dump(), headers={"Cache-Control": "no-store"})


@router.get("/api/statements/{statement_id}/summary")
async def get_category_summary(
    statement_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """The per-category totals and shares of one statement (BE-12). Read as a
    string, so a malformed id is the same 404 as an unknown one (spec 3.1)."""
    try:
        parsed = uuid.UUID(statement_id)
    except ValueError:
        return refusal_response(REFUSED_NOT_FOUND)
    try:
        view = await run_in_threadpool(read_category_summary, session, user, parsed)
    except DBAPIError as exc:
        # The class name only: a driver message can hold the host (spec 3.6).
        log_event("WARNING", "database_error", error=type(exc).__name__)
        raise AccessError(*DATABASE_UNAVAILABLE) from None
    if view is None:
        return refusal_response(REFUSED_NOT_FOUND)
    return JSONResponse(view.model_dump(), headers={"Cache-Control": "no-store"})
