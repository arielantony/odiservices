import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(env="dev")


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    return TestClient(create_app(test_settings))
