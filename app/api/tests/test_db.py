import pytest
from pydantic import SecretStr
from sqlalchemy.pool import QueuePool

from server.db import DatabaseInfo, build_engine, check_database
from server.db.__main__ import run
from server.settings import Settings

URL = SecretStr("postgresql+psycopg://u:SENHA-FICTICIA@127.0.0.1:5432/x")


class FakeResult:
    def one(self):
        return ("app_backend", "170011")


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        return FakeResult()


class FakeEngine:
    def connect(self):
        return FakeConnection()


class FailingEngine:
    def connect(self):
        raise RuntimeError("connection to db.example.com as u failed")


def settings_with(url) -> Settings:
    return Settings(_env_file=None, env="dev", PORTAL_DATABASE_URL=url)


def test_engine_options():
    engine = build_engine(URL)
    pool = engine.pool
    assert isinstance(pool, QueuePool)
    assert (pool.size(), pool._max_overflow) == (3, 2)
    assert pool._pre_ping is True
    assert pool._recycle == 300
    assert engine.echo is False


def test_engine_connect_args(monkeypatch):
    captured = {}
    import sqlalchemy

    real = sqlalchemy.create_engine
    monkeypatch.setattr(
        "server.db.engine.create_engine",
        lambda url, **kw: captured.update(kw) or real(url, **kw),
    )
    build_engine(URL)
    assert captured["connect_args"] == {
        "prepare_threshold": None,
        "connect_timeout": 5,
        "application_name": "odiservices-api",
    }
    assert captured["echo"] is False


def test_engine_url_is_psycopg():
    assert build_engine(URL).dialect.driver == "psycopg"


def test_check_database_returns_role_and_major():
    assert check_database(FakeEngine()) == DatabaseInfo("app_backend", 17)


def test_cli_success_line(capsys):
    code = run(settings_with("postgresql+psycopg://u@127.0.0.1/x"), FakeEngine())
    assert code == 0
    assert capsys.readouterr().out.strip() == "database ok (role=app_backend, postgres=17)"


def test_cli_failure_prints_class_only(capsys):
    code = run(settings_with("postgresql+psycopg://u@127.0.0.1/x"), FailingEngine())
    out = capsys.readouterr().out
    assert code == 1
    assert out.strip() == "database unavailable: RuntimeError"
    assert "db.example.com" not in out


def test_cli_not_configured(capsys):
    assert run(Settings(_env_file=None, env="dev")) == 1
    assert capsys.readouterr().out.strip() == "database not configured"
