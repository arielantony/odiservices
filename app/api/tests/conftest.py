import os

import pytest
from fastapi.testclient import TestClient

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
    """Register a test route on an app built by create_app()."""

    def decorator(func):
        app.get(path)(func)
        return func

    return decorator
