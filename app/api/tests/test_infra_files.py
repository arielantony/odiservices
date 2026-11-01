import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOFU = ROOT / "infra" / "tofu"
main = (TOFU / "main.tf").read_text()
variables = (TOFU / "variables.tf").read_text()
versions = (TOFU / "versions.tf").read_text()
launch = (TOFU / "launch.sh").read_text()
gitignore = (ROOT / ".gitignore").read_text()


def test_only_ssh_is_opened():
    assert main.count("port_info {") == 1
    assert 'protocol  = "tcp"' in main
    assert "from_port = 22" in main and "to_port   = 22" in main
    assert not re.search(r"(?:from|to)_port\s*=\s*(80|443)\b", main)


def test_ssh_cidr_has_no_default_and_rejects_open_world():
    block = variables.split('variable "ssh_allowed_cidrs"')[1]
    assert "default" not in block
    assert "0.0.0.0/0" in block and "::/0" in block


def test_provider_is_pinned_and_lock_file_committed():
    assert re.search(r'version\s*=\s*"= \d+\.\d+\.\d+"', versions)
    assert (TOFU / ".terraform.lock.hcl").is_file()


def test_no_secret_in_infra():
    for path in TOFU.iterdir():
        if not path.is_file() or path.name == ".terraform.lock.hcl":
            continue
        text = path.read_text()
        assert "AKIA" not in text, path.name
        assert "BEGIN OPENSSH PRIVATE KEY" not in text, path.name
        assert not re.search(r"(private_key|secret|token|password)\s*=", text, re.I), path.name


def test_launch_script_hardens_ssh():
    assert "PasswordAuthentication no" in launch
    assert "PermitRootLogin no" in launch
    assert "install -d -m 0700 -o root -g root /etc/odiservices" in launch


def test_launch_script_is_posix_sh():
    # Lightsail does not read cloud-config, and it runs the script inside its own
    # "#!/bin/sh" wrapper, which is dash on Ubuntu: bash-only syntax fails before it starts.
    assert launch.startswith("#!/bin/sh\n")
    assert "#cloud-config" not in launch
    assert "set -eux" in launch
    for bashism in ("pipefail", ">(", "<(", "[[", "function "):
        assert bashism not in launch, bashism


def test_state_files_are_ignored():
    for pattern in ("*.tfstate", ".terraform/", "*.tfvars"):
        assert pattern in gitignore.splitlines()
