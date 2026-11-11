import importlib
import json
import pkgutil
import re

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import server.routes
from server.access import PUBLIC_ROUTES, AccessVerifier
from server.main import create_app
from server.settings import Settings
from tests.access_helpers import AUD, EMAIL, TEAM, FakeKeyClient, make_token

HEADER = "Cf-Access-Jwt-Assertion"
UNAUTHORIZED = {
    "error": {
        "code": "unauthorized",
        "message": "Sessão inválida ou expirada. Entre novamente.",
    }
}
UNAVAILABLE = {
    "error": {
        "code": "auth_unavailable",
        "message": "Não foi possível verificar sua sessão. Tente novamente.",
    }
}


def build_app(error=None):
    settings = Settings(env="dev", access_team_domain=TEAM, access_aud=AUD)
    verifier = AccessVerifier(TEAM, AUD, FakeKeyClient(error))
    return create_app(settings, access_verifier=verifier)


def build(error=None) -> TestClient:
    return TestClient(build_app(error))


def test_no_header_is_401():
    response = build().get("/api/session")

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert response.headers["cache-control"] == "no-store"


def test_valid_token_is_200():
    response = build().get("/api/session", headers={HEADER: make_token()})

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert "@" not in response.text


def test_invalid_token_is_401():
    response = build().get("/api/session", headers={HEADER: "aaa.bbb.ccc"})

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED


def test_only_the_access_header_counts():
    client = build()
    token = make_token()

    by_cookie = client.get("/api/session", cookies={"CF_Authorization": token})
    by_bearer = client.get(
        "/api/session", headers={"Authorization": f"Bearer {token}"}
    )

    assert by_cookie.status_code == 401
    assert by_bearer.status_code == 401


def test_healthz_is_public():
    assert build().get("/healthz").status_code == 200


def test_every_route_is_protected_except_the_list():
    client = build()
    # Every router module under server/routes/ (FastAPI's own route list wraps
    # included routers in a private type), plus whatever the OpenAPI schema
    # lists. A new module is covered without editing this test.
    paths = set(client.app.openapi()["paths"])
    for module in pkgutil.iter_modules(server.routes.__path__):
        router = importlib.import_module(f"server.routes.{module.name}").router
        paths |= {r.path for r in router.routes if isinstance(r, APIRoute)}

    assert {"/api/session", "/healthz"} <= paths
    for path in paths:
        if path in PUBLIC_ROUTES:
            continue
        # A path parameter is filled with a sample id (BE-10).
        url = re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000000", path)
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            response = client.request(method, url)
            assert response.status_code in (401, 405), (method, path)


def test_keys_unavailable_is_503():
    response = build(jwt.PyJWKClientConnectionError("rede")).get(
        "/api/session", headers={HEADER: make_token()}
    )

    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_not_configured_is_503_and_healthz_ok(capsys):
    client = TestClient(create_app(Settings(env="dev")))
    startup = capsys.readouterr().out.strip().splitlines()

    session = client.get("/api/session", headers={HEADER: make_token()})
    health = client.get("/healthz")

    assert [json.loads(line)["event"] for line in startup] == [
        "access_not_configured"
    ]
    assert json.loads(startup[0])["level"] == "WARNING"
    assert session.status_code == 503
    assert session.json() == UNAVAILABLE
    assert health.status_code == 200


def test_token_and_email_never_logged(capsys):
    client = build()
    token = make_token()
    capsys.readouterr()

    client.get("/api/session", headers={HEADER: token})
    client.get("/api/session", headers={HEADER: token + "x"})
    build(OSError("rede")).get("/api/session", headers={HEADER: token})

    out = capsys.readouterr().out
    assert out
    assert token not in out
    assert token.split(".")[1] not in out
    assert EMAIL not in out
    assert "@" not in out


@pytest.mark.parametrize("method", ["get", "post"])
def test_unmatched_route_is_still_404_not_401(method):
    response = getattr(build(), method)("/api/nao-existe")

    assert response.status_code == 404
