import os

import pytest
from fastapi.testclient import TestClient

from server.access import require_access
from server.main import create_app
from server.settings import Settings

os.environ.setdefault("PORTAL_ENV", "dev")


@pytest.fixture
def test_settings() -> Settings:
    return Settings(env="dev")


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    return TestClient(create_app(test_settings))


def add_get(app, path: str):
    """Register a test route on an app built by create_app().

    These apps test other behavior (the log, the headers), so the Access
    check is switched off for them. The Access tests build their own app.
    """
    app.dependency_overrides[require_access] = lambda: None

    def decorator(func):
        app.get(path)(func)
        return func

    return decorator
