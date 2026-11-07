from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from server.access import (
    AccessError,
    AccessVerifier,
    log_not_configured,
    require_access,
)
from server.db import build_engine
from server.request_log import RequestLogMiddleware
from server.routes import health, me, session
from server.security_headers import SecurityHeadersMiddleware
from server.settings import Settings, get_settings

NOT_FOUND = {"error": {"code": "not_found", "message": "Recurso não encontrado."}}


async def not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(NOT_FOUND, status_code=404)


async def access_refused(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AccessError)
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message}},
        status_code=exc.status,
        headers={"Cache-Control": "no-store"},
    )


def build_access_verifier(settings: Settings) -> AccessVerifier | None:
    if settings.access_team_domain is None or settings.access_aud is None:
        log_not_configured()
        return None
    return AccessVerifier(settings.access_team_domain, settings.access_aud)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    if app.state.engine is not None:
        app.state.engine.dispose()


def create_app(
    settings: Settings | None = None,
    access_verifier: AccessVerifier | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    # Deny by default: every route needs a valid Access token except the
    # ones in access.PUBLIC_ROUTES (BE-23).
    app = FastAPI(dependencies=[Depends(require_access)], lifespan=lifespan)
    app.state.settings = settings or get_settings()
    app.state.access_verifier = access_verifier or build_access_verifier(
        app.state.settings
    )
    # The engine is lazy: nothing connects until a request needs the database
    # (BE-24). With no PORTAL_DATABASE_URL there is none, and those requests
    # answer 503.
    if engine is None and app.state.settings.database_url is not None:
        engine = build_engine(app.state.settings.database_url)
    app.state.engine = engine
    # Order matters (BE-17 spec 3.2): middleware (BE-21), then the API
    # routers (BE-20 and later). The API serves no files (BE-33).
    app.add_middleware(
        RequestLogMiddleware,
        traceback=app.state.settings.env == "dev",
    )
    # Outermost, so the 500 response the request log writes carries them too.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(404, not_found)
    app.add_exception_handler(AccessError, access_refused)
    app.include_router(health.router)
    app.include_router(session.router)
    app.include_router(me.router)
    return app
