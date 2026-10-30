from server.main import create_app


def test_healthz_ok(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_healthz_rejects_other_methods(client):
    assert client.post("/healthz").status_code == 405
    assert client.head("/healthz").status_code == 405


def test_healthz_not_in_openapi():
    assert "/healthz" not in create_app().openapi()["paths"]
