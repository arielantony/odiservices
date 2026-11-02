from pathlib import Path

import pytest
from pydantic import ValidationError

from server.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    monkeypatch.delenv("PORTAL_LOG_LEVEL", raising=False)
    monkeypatch.delenv("PORTAL_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("PORTAL_ACCESS_AUD", raising=False)


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


TEAM = "exemplo.cloudflareaccess.com"
AUD = "0123456789abcdef" * 4


def test_access_settings_optional():
    settings = load()

    assert settings.access_team_domain is None
    assert settings.access_aud is None


def test_access_settings_both_or_none(monkeypatch):
    monkeypatch.setenv("PORTAL_ACCESS_TEAM_DOMAIN", TEAM)

    with pytest.raises(ValidationError) as error:
        load()

    assert "PORTAL_ACCESS_AUD" in str(error.value)


def test_access_settings_set_together(monkeypatch):
    monkeypatch.setenv("PORTAL_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("PORTAL_ACCESS_AUD", AUD)

    settings = load()

    assert (settings.access_team_domain, settings.access_aud) == (TEAM, AUD)


def test_blank_access_settings_count_as_unset(monkeypatch):
    # A .env copied from .env.example has the names with no value.
    monkeypatch.setenv("PORTAL_ACCESS_TEAM_DOMAIN", "")
    monkeypatch.setenv("PORTAL_ACCESS_AUD", "")

    assert load().access_aud is None


@pytest.mark.parametrize(
    "domain", ["evil.example.com", f"{TEAM}.evil.com", "https://" + TEAM]
)
def test_access_team_domain_pattern(monkeypatch, domain):
    monkeypatch.setenv("PORTAL_ACCESS_TEAM_DOMAIN", domain)
    monkeypatch.setenv("PORTAL_ACCESS_AUD", AUD)

    with pytest.raises(ValidationError) as error:
        load()

    assert "PORTAL_ACCESS_TEAM_DOMAIN" in str(error.value)
    assert domain not in str(error.value)


def test_access_aud_pattern(monkeypatch):
    monkeypatch.setenv("PORTAL_ACCESS_TEAM_DOMAIN", TEAM)
    monkeypatch.setenv("PORTAL_ACCESS_AUD", "valor-curto-secreto")

    with pytest.raises(ValidationError) as error:
        load()

    assert "PORTAL_ACCESS_AUD" in str(error.value)
    assert "valor-curto-secreto" not in str(error.value)
