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
    monkeypatch.delenv("PORTAL_DATABASE_URL", raising=False)


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


REMOTE = "postgresql+psycopg://u:SENHA-FICTICIA@db.example.com/x"


def with_db(monkeypatch, url, env="prod") -> Settings:
    monkeypatch.setenv("PORTAL_ENV", env)
    monkeypatch.setenv("PORTAL_DATABASE_URL", url)
    return load()


def test_database_url_optional():
    assert load().database_url is None


def test_blank_database_url_counts_as_unset(monkeypatch):
    monkeypatch.setenv("PORTAL_DATABASE_URL", "")
    assert load().database_url is None


@pytest.mark.parametrize(
    "url", ["postgresql://u@127.0.0.1/x", "mysql://u@127.0.0.1/x", "x"]
)
def test_database_url_scheme(monkeypatch, url):
    with pytest.raises(ValidationError, match="PORTAL_DATABASE_URL"):
        with_db(monkeypatch, url)


@pytest.mark.parametrize(
    "url",
    ["postgresql+psycopg://u@127.0.0.1", "postgresql+psycopg://u@127.0.0.1/",
     "postgresql+psycopg:///x"],
)
def test_database_url_needs_host_and_name(monkeypatch, url):
    with pytest.raises(ValidationError, match="PORTAL_DATABASE_URL"):
        with_db(monkeypatch, url)


@pytest.mark.parametrize("query", ["", "?sslmode=disable", "?sslmode=prefer"])
def test_remote_host_needs_tls(monkeypatch, query):
    with pytest.raises(ValidationError, match="PORTAL_DATABASE_URL"):
        with_db(monkeypatch, REMOTE + query)


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_remote_host_with_tls_passes(monkeypatch, mode):
    settings = with_db(monkeypatch, f"{REMOTE}?sslmode={mode}")
    assert settings.database_url is not None


@pytest.mark.parametrize("host", ["127.0.0.1", "[::1]", "localhost"])
def test_loopback_host_needs_no_tls(monkeypatch, host):
    url = f"postgresql+psycopg://u@{host}:5432/x"
    assert with_db(monkeypatch, url).database_url is not None


def test_dev_refuses_remote_host(monkeypatch):
    with pytest.raises(ValidationError, match="PORTAL_DATABASE_URL"):
        with_db(monkeypatch, REMOTE + "?sslmode=require", env="dev")
    local = "postgresql+psycopg://u@127.0.0.1/x"
    assert with_db(monkeypatch, local, env="dev").database_url is not None
    assert with_db(monkeypatch, REMOTE + "?sslmode=require").database_url is not None


def test_database_url_never_printed(monkeypatch):
    messages = []
    for url, env in [
        (REMOTE, "prod"),
        (REMOTE + "?sslmode=require", "dev"),
        ("postgresql://u:SENHA-FICTICIA@127.0.0.1/x", "prod"),
    ]:
        with pytest.raises(ValidationError) as error:
            with_db(monkeypatch, url, env=env)
        messages.append(str(error.value))
    settings = with_db(monkeypatch, REMOTE + "?sslmode=require")
    messages += [repr(settings), str(settings)]
    assert all("SENHA-FICTICIA" not in message for message in messages)
