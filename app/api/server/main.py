from pathlib import Path

from fastapi import FastAPI

from server.frontend import install_frontend
from server.request_log import RequestLogMiddleware
from server.routes import health
from server.security_headers import SecurityHeadersMiddleware
from server.settings import Settings, get_settings


def create_app(
    settings: Settings | None = None, frontend_dir: Path | None = None
) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings or get_settings()
    # Order matters (BE-17 spec 3.2): middleware (BE-21), API routers
    # (BE-20 and later), then the frontend mount and SPA fallback (BE-01),
    # so nothing shadows a route.
    app.add_middleware(
        RequestLogMiddleware,
        traceback=app.state.settings.env == "dev",
    )
    # Outermost, so the 500 response the request log writes carries them too.
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health.router)
    install_frontend(app, frontend_dir, app.state.settings.env)
    return app


def __getattr__(name: str) -> FastAPI:
    # Built on first access (uvicorn's `server.main:app`), so importing this
    # module never needs web/dist/ (BE-01 spec 3.2).
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
