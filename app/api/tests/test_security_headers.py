from fastapi.testclient import TestClient

from server.main import create_app

API_CSP = "default-src 'none'; frame-ancestors 'none'"


def test_api_csp_on_every_response(client):
    for path in ("/healthz", "/api/nope"):
        response = client.get(path)

        assert response.headers.get_list("content-security-policy") == [API_CSP]


def test_csp_on_a_500():
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.headers["content-security-policy"] == API_CSP


def test_existing_headers_unchanged(client):
    response = client.get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "DENY"
