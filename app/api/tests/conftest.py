import os

import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import Settings

# create_app() with default settings must not need web/dist/ (BE-01).
os.environ.setdefault("PORTAL_ENV", "dev")


@pytest.fixture
def test_settings() -> Settings:
    return Settings(env="dev")


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    return TestClient(create_app(test_settings))


def add_get(app, path: str):
    """Register a test route ahead of the frontend fallback (BE-01).

    Routes added after create_app() land behind the catch-all, so they are
    moved to the front.
    """

    def decorator(func):
        app.get(path)(func)
        app.router.routes.insert(0, app.router.routes.pop())
        return func

    return decorator
