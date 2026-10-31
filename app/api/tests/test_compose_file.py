from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
text = COMPOSE.read_text()
services = yaml.safe_load(text)["services"]


def test_has_api_and_web_services():
    assert set(services) == {"api", "web"}
    assert services["api"]["build"]["context"] == "api"
    assert services["web"]["build"]["context"] == "web"


def test_only_web_publishes_a_port_on_loopback():
    assert "ports" not in services["api"]
    assert services["web"]["ports"]
    assert all(port.startswith("127.0.0.1:") for port in services["web"]["ports"])


def test_env_file_is_optional_and_api_only():
    assert services["api"]["env_file"] == [{"path": ".env", "required": False}]
    assert "env_file" not in services["web"]


def test_no_secret_or_data_in_file():
    for word in ("SUPABASE", "KEY", "SECRET", "TOKEN"):
        assert word not in text
    assert "volumes" not in text
    assert all("volumes" not in service for service in services.values())


def test_containers_are_locked_down():
    for service in services.values():
        assert service["read_only"] is True
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]


def test_web_waits_for_a_healthy_api():
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
