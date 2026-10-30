from fastapi import FastAPI

from server.request_log import RequestLogMiddleware
from server.routes import health
from server.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings or get_settings()
    # Order matters (BE-17 spec 3.2): middleware (BE-21), API routers
    # (BE-20 and later), then the frontend mount and SPA fallback (BE-01),
    # so nothing shadows a route.
    app.add_middleware(
        RequestLogMiddleware,
        traceback=app.state.settings.env == "dev",
    )
    app.include_router(health.router)
    return app


app = create_app()
