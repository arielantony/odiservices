from starlette.routing import Mount

from server.main import create_app
from server.settings import Settings


def test_create_app_returns_independent_instances():
    first, second = create_app(), create_app()

    @first.get("/only-first")
    def only_first():
        return {}

    assert first is not second
    assert "/only-first" in {route.path for route in first.routes}
    assert "/only-first" not in {route.path for route in second.routes}


def test_create_app_accepts_explicit_settings(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "from-environment")
    settings = Settings(env="dev")

    assert create_app(settings).state.settings is settings


def test_routes_registered_before_static_mount():
    routes = create_app().routes
    mounts = [i for i, route in enumerate(routes) if isinstance(route, Mount)]

    assert all(i == len(routes) - 1 for i in mounts)
