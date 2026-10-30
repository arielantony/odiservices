import json

import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import Settings

INDEX = "<!doctype html><title>Portal Fictício</title>"
SECURITY = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
}


@pytest.fixture
def site(tmp_path):
    """A fictitious dist/ with a .env and a secret.txt next to it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "app-abc123.js").write_text("console.log('ok')")
    (dist / "favicon.ico").write_bytes(b"ico")
    (tmp_path / ".env").write_text("SEGREDO=valor-fictício")
    (tmp_path / "secret.txt").write_text("segredo-fictício")
    return dist


@pytest.fixture
def client(test_settings, site):
    return TestClient(create_app(test_settings, frontend_dir=site))


def test_root_serves_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == INDEX


def test_client_routes_fall_back_to_index(client):
    for path in ("/categorizer", "/categorizer/", "/categorizer/abc-123"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == INDEX
        assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_immutable(client):
    response = client.get("/assets/app-abc123.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "immutable" in response.headers["cache-control"]


def test_root_file_is_served(client):
    assert client.get("/favicon.ico").content == b"ico"


def test_missing_file_with_extension_is_404(client):
    for path in ("/missing.js", "/assets/missing.js", "/assets/nope"):
        response = client.get(path)
        assert response.status_code == 404
        assert INDEX not in response.text


def test_unknown_api_path_is_json_404(client):
    for response in (client.get("/api/nao-existe"), client.post("/api/nao-existe")):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_traversal_is_blocked(client):
    for path in ("/../.env", "/%2e%2e/.env", "/../secret.txt", "/%2e%2e/secret.txt"):
        response = client.get(path)
        assert response.status_code == 404
        assert "valor-fictício" not in response.text
        assert "segredo-fictício" not in response.text


def test_security_headers_on_every_response(client):
    for path in ("/", "/assets/app-abc123.js", "/api/nao-existe", "/missing.js", "/healthz"):
        headers = client.get(path).headers
        for name, value in SECURITY.items():
            assert headers[name] == value, path


def test_static_file_logged_by_path(client, capsys):
    client.get("/assets/app-abc123.js?x=fulano@exemplo.com")

    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert line["route"] == "/assets/app-abc123.js"
    assert "@" not in json.dumps(line)


def test_client_route_logged_as_unmatched(client, capsys):
    client.get("/categorizer/abc-123")

    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert line["route"] == "unmatched"


def test_healthz_not_shadowed(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_missing_dist_fails_in_prod(tmp_path):
    with pytest.raises(RuntimeError, match="make build-web"):
        create_app(Settings(env="prod"), frontend_dir=tmp_path / "nope")


def test_missing_dist_is_503_in_dev(test_settings, tmp_path):
    client = TestClient(create_app(test_settings, frontend_dir=tmp_path / "nope"))

    assert client.get("/").status_code == 503
    assert "make build-web" in client.get("/").text
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/x").status_code == 404
