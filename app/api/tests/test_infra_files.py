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


BOOTSTRAP = ROOT / "infra" / "tofu-bootstrap"


def test_bootstrap_bucket_is_hardened():
    text = (BOOTSTRAP / "main.tf").read_text()
    assert 'status = "Enabled"' in text
    assert 'sse_algorithm = "AES256"' in text
    for setting in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert re.search(rf"{setting}\s*=\s*true", text), setting
    assert 'object_ownership = "BucketOwnerEnforced"' in text
    assert '"aws:SecureTransport"' in text and 'values   = ["false"]' in text
    assert "noncurrent_days = 90" in text
    assert "prevent_destroy = true" in text


def test_bootstrap_provider_matches_main():
    pin = re.search(r'version\s*=\s*"(= \d+\.\d+\.\d+)"', versions)
    other = re.search(
        r'version\s*=\s*"(= \d+\.\d+\.\d+)"', (BOOTSTRAP / "versions.tf").read_text()
    )
    assert pin and other and pin.group(1) == other.group(1)
    assert (BOOTSTRAP / ".terraform.lock.hcl").is_file()


def test_bootstrap_has_no_bucket_name_default():
    block = (BOOTSTRAP / "variables.tf").read_text().split('variable "bucket_name"')[1]
    assert "default" not in block.split("validation")[0]
    assert "<account-id>" in (BOOTSTRAP / "terraform.tfvars.example").read_text()


def test_state_and_backend_files_are_ignored():
    lines = gitignore.splitlines()
    assert "*.tfstate" in lines and "*.tfvars" in lines and "backend.hcl" in lines
    assert "!*.tfvars.example" in lines


def test_backend_is_partial_and_locked():
    backend = (TOFU / "backend.tf").read_text()
    assert 'backend "s3" {}' in backend
    code = "\n".join(l for l in backend.splitlines() if not l.lstrip().startswith("#"))
    assert "bucket" not in code and "key" not in code
    example = (TOFU / "backend.hcl.example").read_text()
    assert "encrypt      = true" in example
    assert "use_lockfile = true" in example
    assert "<account-id>" in example


CLOUDFLARE = ROOT / "infra" / "cloudflare"
cf_main = (CLOUDFLARE / "main.tf").read_text()
cf_variables = (CLOUDFLARE / "variables.tf").read_text()
cf_versions = (CLOUDFLARE / "versions.tf").read_text()
cf_outputs = (CLOUDFLARE / "outputs.tf").read_text()


def _block(text, header):
    return text.split(header)[1].split("\n}\n")[0]


def test_cloudflare_dns_depends_on_access():
    dns = _block(cf_main, 'resource "cloudflare_dns_record" "portal"')
    depends = dns.split("depends_on")[1]
    assert "cloudflare_zero_trust_access_application.portal" in depends
    assert "cloudflare_zero_trust_access_policy.allow" in depends


def test_cloudflare_has_no_identifier_defaults():
    for name in ("account_id", "zone_id", "allowed_emails", "allowed_email_domains"):
        assert not re.search(r"^\s*default\s*=", _block(cf_variables, f'variable "{name}"'), re.M), name
    example = (CLOUDFLARE / "terraform.tfvars.example").read_text()
    assert "<cloudflare-account-id>" in example and "<zone-id-of-tripleadev.com.br>" in example
    assert not re.search(r'"[0-9a-f]{32}"', example)
    assert "@" not in example


def test_cloudflare_provider_is_pinned():
    assert re.search(r'version\s*=\s*"= \d+\.\d+\.\d+"', cf_versions)
    assert (CLOUDFLARE / ".terraform.lock.hcl").is_file()


def test_cloudflare_token_is_sensitive():
    assert "sensitive = true" in _block(cf_outputs, 'output "tunnel_token"')
    for path in CLOUDFLARE.iterdir():
        if not path.is_file() or path.name in (".terraform.lock.hcl", "terraform.tfvars", "backend.hcl"):
            continue
        text = path.read_text()
        assert not re.search(r'(token|secret|password)\s*=\s*"[^"]+"', text, re.I), path.name
        assert not re.search(r"\b[0-9a-f]{32}\b", text), path.name


def test_ingress_reaches_web_only():
    ingress = cf_main.split("ingress = [")[1].split("]")[0]
    assert ingress.count("service") == 2
    assert 'service = "http://127.0.0.1:8080"' in ingress
    assert ingress.strip().rstrip(",").endswith('{ service = "http_status:404" }')


def test_firewall_opens_only_ssh():
    assert main.count("port_info {") == 1
    assert "from_port = 22" in main and "to_port   = 22" in main


def test_install_script_keeps_token_private():
    script = (ROOT / "app" / "deploy" / "install-cloudflared.sh").read_text()
    assert "read -r TUNNEL_TOKEN" in script and "[ -t 0 ]" in script
    assert "${1" not in script and "$1" not in script
    assert 'install -m 0600 -o root -g root /dev/null "$ENV_FILE"' in script
    assert "EnvironmentFile=/etc/odiservices/cloudflared.env" in script
    assert not re.search(r"echo[^\n]*TUNNEL_TOKEN", script)
    assert "set -x" not in script
    assert not re.search(r"TUNNEL_TOKEN=[A-Za-z0-9]", script)
