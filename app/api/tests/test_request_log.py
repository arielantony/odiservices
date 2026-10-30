import json
import uuid

import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import Settings


@pytest.fixture
def app(test_settings):
    app = create_app(test_settings)

    @app.get("/api/things/{thing_id}")
    def thing(thing_id: str):
        return {"id": thing_id}

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("Papelaria Fictícia")

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def log_lines(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_one_json_line_per_request(client, capsys):
    client.get("/healthz")

    lines = log_lines(capsys)
    assert len(lines) == 1
    assert set(lines[0]) == {
        "ts", "level", "event", "request_id", "method", "route", "status", "duration_ms",
    }
    assert lines[0]["event"] == "request"
    assert lines[0]["method"] == "GET"
    assert lines[0]["route"] == "/healthz"
    assert lines[0]["status"] == 200


def test_route_template_not_raw_path(client, capsys):
    client.get("/api/things/abc-123")

    assert log_lines(capsys)[0]["route"] == "/api/things/{thing_id}"


def test_no_query_string_logged(client, capsys):
    client.get("/healthz?email=fulano@exemplo.com")

    out = capsys.readouterr().out
    assert "@" not in out
    assert "fulano" not in out
    assert "email" not in out


def test_no_headers_logged(client, capsys):
    client.get(
        "/healthz",
        headers={
            "Cookie": "session=segredo-cookie",
            "Authorization": "Bearer segredo-token",
            "Cf-Access-Jwt-Assertion": "segredo-jwt",
        },
    )

    out = capsys.readouterr().out
    assert "segredo" not in out


def test_request_id_from_cf_ray(client, capsys):
    response = client.get("/healthz", headers={"Cf-Ray": "8a1b2c3d4e5f-GRU"})

    assert log_lines(capsys)[0]["request_id"] == "8a1b2c3d4e5f-GRU"
    assert response.headers["x-request-id"] == "8a1b2c3d4e5f-GRU"


def test_request_id_generated(client, capsys):
    response = client.get("/healthz")

    request_id = log_lines(capsys)[0]["request_id"]
    assert uuid.UUID(request_id).version == 4
    assert response.headers["x-request-id"] == request_id


def test_unsafe_cf_ray_is_replaced(client, capsys):
    client.get("/healthz", headers={"Cf-Ray": "fulano@exemplo.com"})

    out = capsys.readouterr().out
    assert "fulano" not in out


def test_level_by_status(app, capsys):
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/nao-existe")
    response = client.get("/api/boom")

    not_found, error = log_lines(capsys)
    assert not_found["level"] == "WARNING"
    assert not_found["route"] == "unmatched"
    assert error["level"] == "ERROR"
    assert error["status"] == 500
    assert error["exception"] == "RuntimeError"
    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert "Papelaria" not in response.text


def test_traceback_only_in_dev(capsys):
    for env, expected in (("dev", True), ("prod", False)):
        app = create_app(Settings(env=env))

        @app.get("/boom")
        def boom():
            raise RuntimeError("falha")

        TestClient(app, raise_server_exceptions=False).get("/boom")

        assert ("traceback" in log_lines(capsys)[0]) is expected
