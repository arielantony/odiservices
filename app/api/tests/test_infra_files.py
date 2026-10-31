import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOFU = ROOT / "infra" / "tofu"
main = (TOFU / "main.tf").read_text()
variables = (TOFU / "variables.tf").read_text()
versions = (TOFU / "versions.tf").read_text()
cloud_init = (TOFU / "cloud-init.yaml").read_text()
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


def test_cloud_init_hardens_ssh():
    assert "PasswordAuthentication no" in cloud_init
    assert "PermitRootLogin no" in cloud_init
    assert "install -d -m 0700 -o root -g root /etc/odiservices" in cloud_init


def test_state_files_are_ignored():
    for pattern in ("*.tfstate", ".terraform/", "*.tfvars"):
        assert pattern in gitignore.splitlines()
