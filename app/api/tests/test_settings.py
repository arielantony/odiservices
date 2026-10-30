from pathlib import Path

import pytest
from pydantic import ValidationError

from server.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    monkeypatch.delenv("PORTAL_LOG_LEVEL", raising=False)


def load() -> Settings:
    return Settings(_env_file=None)


def test_defaults_to_prod():
    settings = load()

    assert settings.env == "prod"
    assert settings.log_level == "INFO"


def test_reads_prefixed_variables(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "dev")
    monkeypatch.setenv("PORTAL_LOG_LEVEL", "DEBUG")

    settings = load()

    assert (settings.env, settings.log_level) == ("dev", "DEBUG")


def test_rejects_unknown_env(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "staging")

    with pytest.raises(ValidationError) as error:
        load()

    assert "PORTAL_ENV" in str(error.value)


def test_error_does_not_echo_value(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "staging-secret-value")

    with pytest.raises(ValidationError) as error:
        load()

    assert "staging-secret-value" not in str(error.value)


def test_env_example_lists_every_field():
    lines = [
        line for line in ENV_EXAMPLE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    names = {line.split("=", 1)[0] for line in lines}

    assert names == {field.alias for field in Settings.model_fields.values()}
    assert all(line.split("=", 1)[1] == "" for line in lines)
