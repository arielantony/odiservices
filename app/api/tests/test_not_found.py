import json

from fastapi.testclient import TestClient

from server.main import create_app
from server.settings import Settings

BODY = {"error": {"code": "not_found", "message": "Recurso não encontrado."}}


def test_unknown_api_path_is_json_404(client):
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response.json() == BODY


def test_unknown_page_path_is_json_404(client):
    for path in ("/", "/categorizer", "/.env"):
        response = client.get(path)

        assert response.status_code == 404
        assert response.json() == BODY
        assert "html" not in response.headers["content-type"]


def test_security_headers_on_404(client):
    response = client.get("/api/nope")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "DENY"


def test_boots_in_prod_without_a_frontend():
    client = TestClient(create_app(Settings(env="prod")))

    assert client.get("/healthz").json() == {"status": "ok"}


def test_unmatched_404_is_logged_without_the_path(client, capsys):
    client.get("/api/segredo-fictício?q=1")

    out = capsys.readouterr().out
    assert json.loads(out)["route"] == "unmatched"
    assert "segredo" not in out
