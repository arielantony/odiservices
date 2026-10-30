from fastapi import FastAPI

from server.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings or Settings()
    # Order matters (BE-17 spec 3.2): middleware (BE-21), API routers
    # (BE-20 and later), then the frontend mount and SPA fallback (BE-01),
    # so nothing shadows a route.
    return app


app = create_app()
