import re
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2]
SCRIPT = (APP / "deploy" / "deploy.sh").read_text()


class _Loader(yaml.SafeLoader):
    pass


# `!override` replaces the base value instead of merging it.
_Loader.add_constructor(
    "!override",
    lambda loader, node: ("override", loader.construct_sequence(node)),
)


def _load(name):
    return yaml.load((APP / name).read_text(), Loader=_Loader)["services"]


def _merged():
    base, prod = _load("docker-compose.yml"), _load("docker-compose.prod.yml")
    merged = {}
    for name, svc in base.items():
        merged[name] = dict(svc)
        for key, value in prod[name].items():
            if isinstance(value, tuple) and value[0] == "override":
                value = value[1]
            merged[name][key] = value
    return merged


def test_prod_override_keeps_lockdown():
    for svc in _merged().values():
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in svc["security_opt"]


def test_only_web_publishes_a_loopback_port():
    merged = _merged()
    assert "ports" not in merged["api"]
    assert len(merged["web"]["ports"]) == 1
    assert merged["web"]["ports"][0].startswith("127.0.0.1:")


def test_restart_policy_is_unless_stopped():
    for svc in _merged().values():
        assert svc["restart"] == "unless-stopped"


def test_env_file_is_outside_the_repo():
    assert _merged()["api"]["env_file"] == ["/etc/odiservices/.env"]


def test_no_secret_or_volume_in_prod_file():
    text = (APP / "docker-compose.prod.yml").read_text()
    assert not re.search(r"SUPABASE|KEY|SECRET|TOKEN", text)
    for svc in _merged().values():
        assert "volumes" not in svc


def test_deploy_script_is_safe():
    assert SCRIPT.splitlines()[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in SCRIPT
    assert "set -x" not in SCRIPT
    assert "printenv" not in SCRIPT
    assert not re.search(r"\b(cat|less|more|tail|head)\b[^\n|]*\$ENV_FILE", SCRIPT)
