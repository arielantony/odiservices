from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.request_log import RequestLogMiddleware
from server.routes import health
from server.security_headers import SecurityHeadersMiddleware
from server.settings import Settings, get_settings

NOT_FOUND = {"error": {"code": "not_found", "message": "Recurso não encontrado."}}


async def not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(NOT_FOUND, status_code=404)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings or get_settings()
    # Order matters (BE-17 spec 3.2): middleware (BE-21), then the API
    # routers (BE-20 and later). The API serves no files (BE-33).
    app.add_middleware(
        RequestLogMiddleware,
        traceback=app.state.settings.env == "dev",
    )
    # Outermost, so the 500 response the request log writes carries them too.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(404, not_found)
    app.include_router(health.router)
    return app
