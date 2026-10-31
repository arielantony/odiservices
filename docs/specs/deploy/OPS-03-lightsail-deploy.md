# Spec — OPS-03 Deploy to AWS Lightsail

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-03 |
| **Depends on** | OPS-01, OPS-02, BE-32 |
| **Spec status** | Draft, awaiting the owner's approval. Owner decisions of 2026-10-31 are applied: OpenTofu, `us-east-2` (Ohio), the 4 GB plan (dual-stack), local state first, containers, a private repo with a deploy key, and owner-run checks |
| **Date** | 2026-10-31 |

## 1. Goal

Create one Lightsail instance with OpenTofu, and run the two images (OPS-01) on
it with Compose, restarted by Docker. The owner reaches the portal over an SSH
tunnel and tests the real host. The instance is **not** public yet: Cloudflare
and Access come in OPS-04, and the portal has no auth until BE-23. Until then
nothing listens on a public web port.

## 2. Scope

**In scope**

- `infra/tofu/`: the OpenTofu configuration for the instance (section 3.2).
- `app/docker-compose.prod.yml`, an override of `docker-compose.yml` (OPS-02)
  for the host.
- `app/deploy/deploy.sh`, run **on the host**: update the checkout, build,
  restart, wait for health, roll back on failure.
- `docs/deploy/lightsail.md`, the runbook: credentials, `tofu apply`, first
  deploy, update, rollback, reach the portal, destroy.
- `make infra-check` and `make deploy-check` (section 6).

**Out of scope**

- Cloudflare, Tunnel, Access and the firewall that restricts the origin to
  Cloudflare: OPS-04.
- How runtime secrets are created, rotated and stored: OPS-05. This item names
  only the file the host reads (3.4).
- A remote state backend (S3 with locking). The owner will move the state
  there later (question 4). It is a separate backlog item.
- A registry, CI and automatic deploys: not in the backlog. The host builds the
  images itself (question 2).
- Backups of data: nothing persists on the host (no volume, no `input/`, no
  `outputs/`).

## 3. Design

### 3.1 Container, not systemd

The previous Lightsail setup ran the app under systemd. This item uses
Compose, because the unit of delivery is already two images with a read-only
root, dropped capabilities and a healthcheck (OPS-01, OPS-02). A systemd unit
would need Python, Node and nginx installed and pinned on the host, and the
"same image as local" guarantee would be lost. Docker's
`restart: unless-stopped` brings the stack back after a crash or a reboot, as
long as the Docker service is enabled at boot.

### 3.2 The infrastructure (`infra/tofu/`)

| File | Content |
|---|---|
| `versions.tf` | `required_version` and `required_providers`: `opentofu/aws` pinned to an exact version. The lock file `.terraform.lock.hcl` **is** committed |
| `variables.tf` | `region` (default `us-east-2`), `availability_zone` (default `us-east-2a`), `bundle_id` (default `medium_3_0`), `blueprint_id` (default `ubuntu_24_04`), `ssh_public_key` (no default), `ssh_allowed_cidrs` (no default) |
| `main.tf` | The resources below |
| `cloud-init.yaml` | The `user_data` template (below) |
| `outputs.tf` | `public_ip` and `ssh_command`. No secret |

Resources:

- `aws_lightsail_key_pair` from the owner's **public** key. No private key is
  ever created by OpenTofu, so none lands in the state.
- `aws_lightsail_instance`, `us-east-2a`, Ubuntu 24.04 LTS, the 4 GB plan
  (`medium_3_0`; the implementer confirms the id with
  `aws lightsail get-bundles --region us-east-2` and the spec is amended if it
  differs, for example the IPv6-only variant).
- `aws_lightsail_static_ip` and its attachment, so the address survives a stop.
- `aws_lightsail_instance_public_ports`: **only TCP 22**, from
  `ssh_allowed_cidrs`. Never `0.0.0.0/0` as a default: the variable has no
  default and a validation rejects `0.0.0.0/0` and `::/0`. No 80, no 443.

`cloud-init.yaml` (the instance's first boot):

1. Installs Docker Engine and the Compose plugin from Docker's apt repository.
2. Enables Docker at boot.
3. Creates a non-root `deploy` user in the `docker` group with the owner's
   public key, and disables SSH password login and root login.
4. Enables unattended upgrades (security only).
5. Creates `/etc/odiservices/` owned by `root`, mode `0700`, and an empty
   `/opt/odiservices` owned by `deploy`. It does **not** clone: the repository
   is private (3.4).

The `user_data` carries **no secret**. The env file is never passed through
OpenTofu, because its values would be stored in the state in plain text.

State: **local** (`terraform.tfstate` in `infra/tofu/`), git-ignored together
with `*.tfstate*`, `.terraform/` and `*.tfvars`. The state holds the instance
and its address, not a key. A `terraform.tfvars.example` lists the variable
names only. The runbook says: back the state file up outside the repo, and do
not run `apply` from two machines.

Credentials: the AWS CLI profile or SSO session on the owner's machine, read by
the provider from the environment. Nothing in the repo names a key. The IAM
user needs only Lightsail permissions (the runbook lists the managed policy
`AmazonLightsailFullAccess`).

### 3.3 The host

| Item | Choice |
|---|---|
| Region and zone | `us-east-2` (Ohio), `us-east-2a` |
| Plan | 4 GB RAM (`medium_3_0`), enough for the web build (`yarn build`) on the host |
| Firewall | TCP 22 from `ssh_allowed_cidrs` only |
| SSH | Key only, `deploy` user. Root and password login off |
| Docker group | Root-equivalent. Only the owner's key is on the `deploy` account |

### 3.4 Files on the host

- `/opt/odiservices`: a checkout of this repository at a tag or a commit. It
  holds no data. The repository is private, so the runbook has the owner,
  once, on the host as `deploy`: run `ssh-keygen -t ed25519` (no passphrase,
  since `deploy.sh` runs unattended), add the **public** key as a read-only
  deploy key in the GitHub repository settings, and `git clone` over SSH. The
  private key is born on the host, mode `0600`, and never passes through
  OpenTofu, the state or the repo.
- `/etc/odiservices/.env`: owned by `root`, mode `0600`. The prod override
  points `env_file` at it. OPS-05 decides its contents. Until then the file
  may be absent or empty and `api` starts on defaults (`prod`). The deploy
  script creates it empty with `0600` if missing, using `sudo`.
- The file is **never** in the checkout, the image, a log, the OpenTofu state
  or a PR.

### 3.5 Reaching the portal before OPS-04

`web` publishes `127.0.0.1:8080` on the host, as in OPS-02. The owner opens
`ssh -L 8080:127.0.0.1:8080 deploy@<ip>` and browses `http://127.0.0.1:8080`.
There is no public listener, so the missing auth (BE-23) exposes nothing.
OPS-04 replaces this with a Cloudflare Tunnel and does not change the images.

### 3.6 `docker-compose.prod.yml`

```yaml
# Used on the Lightsail host only: docker compose -f docker-compose.yml -f docker-compose.prod.yml
services:
  api:
    image: odiservices-api:${DEPLOY_TAG:-current}
    env_file: !override
      - /etc/odiservices/.env
    restart: unless-stopped

  web:
    image: odiservices-web:${DEPLOY_TAG:-current}
    ports: !override
      - "127.0.0.1:8080:8080"
    restart: unless-stopped
```

Everything else (read-only root, `cap_drop`, `no-new-privileges`, the
healthchecks, no volume) is inherited from OPS-02 and must not be loosened.

### 3.7 `deploy.sh`

Run as the `deploy` user, from `/opt/odiservices/app`, with a git ref argument:

1. `git fetch` and check out the ref. Refuse a dirty checkout.
2. Record the tag of the running images (`previous`).
3. Build both images, tagged `odiservices-<svc>:<short sha>`.
4. `DEPLOY_TAG=<short sha> docker compose ... up --detach --wait`.
5. Check `curl -fsS http://127.0.0.1:8080/healthz` and the page `/`.
6. On any failure, `up` again with `previous` and exit non-zero.
7. Remove images older than the last three.

The script prints no environment variable, no env file content and no request
data.

### 3.8 Steps

The item exceeds 500 lines with the two parts, so it ships as two pull
requests (`CLAUDE.md`, "Branches"), on the feature branch
`feature/ops-03-lightsail`:

| Step | Branch | Content |
|---|---|---|
| 1 | `feat/ops-03-step-1-infra` | `infra/tofu/`, `.gitignore` entries, `make infra-check`, `test_infra_files.py`, the runbook's infrastructure half |
| 2 | `feat/ops-03-step-2-deploy` | `docker-compose.prod.yml`, `deploy.sh`, `make deploy-check`, `test_deploy_files.py`, the runbook's deploy half, the `CLAUDE.md` line |

Then a final PR takes the feature branch to `main`. The owner-run checks in
section 4 happen on that final PR.

## 4. Verification

Checks 1 to 5 need only this repository and run at each step's merge. Checks 6
to 15 need the owner's AWS account, so **the owner runs them with the
implementer present** and the PR records "validated on <date>", with no
addresses and no keys (question 6).

| # | Step | Check | Expected |
|---|---|---|---|
| 1 | 1 | `make infra-check` (`tofu fmt -check`, `tofu init -backend=false`, `tofu validate`) | Passes, with no AWS credentials |
| 2 | 1 | `test_infra_files.py` | Passes (section 6) |
| 3 | 1 | `git check-ignore infra/tofu/terraform.tfstate infra/tofu/.terraform infra/tofu/terraform.tfvars` | All three are ignored |
| 4 | 2 | `make deploy-check` (the merged Compose files and `shellcheck` when installed) | Passes. `api` has no `ports`. `web` publishes only `127.0.0.1:8080`. Both have `restart: unless-stopped`, `read_only`, `cap_drop: [ALL]` |
| 5 | 2 | `shellcheck app/deploy/deploy.sh` | No findings |
| 6 | final | `tofu plan` with the owner's `tfvars` | Creates a key pair, an instance, a static IP, its attachment and the port rule. No destroy |
| 7 | final | `tofu apply`, then `ssh deploy@<ip> docker --version` | The instance exists, Docker is installed, and the `deploy` user can run it |
| 8 | final | `ssh root@<ip>` and an SSH attempt with a password | Both refused |
| 9 | final | Scan the public IP (`nmap -Pn -p 1-65535`) | Only 22 is open |
| 10 | final | `deploy.sh <ref>` on the host | Ends with both containers `healthy` |
| 11 | final | `ssh -L` tunnel, then `curl` `/healthz`, `/` and `/api/nope` on the forwarded port | 200 `ok`, 200 HTML, 404 `not_found` JSON. The CSP headers of BE-32 are present |
| 12 | final | `sudo reboot`, wait, repeat check 11 | The stack came back with no manual step |
| 13 | final | `docker kill` the `api` container | Docker restarts it and `/healthz` recovers |
| 14 | final | Deploy a ref whose `web` healthcheck fails (a deliberately broken commit on a scratch branch) | `deploy.sh` exits non-zero and the previous tag is serving again |
| 15 | final | `stat -c '%U %a' /etc/odiservices/.env`, `grep -ci 'key\|secret\|token' infra/tofu/terraform.tfstate` and `docker compose exec api sh -c 'find /app -name ".env*"'` | `root 600`. The state holds no secret. Nothing found in the container |

Then `tofu destroy` removes the instance if it was a throwaway, and the
address is released.

## 5. Files

| File | Step | Change |
|---|---|---|
| `infra/tofu/*.tf`, `cloud-init.yaml`, `terraform.tfvars.example`, `.terraform.lock.hcl` | 1 | New. Section 3.2 |
| `.gitignore` | 1 | State, `.terraform/`, `*.tfvars` |
| `app/Makefile` | 1, 2 | `infra-check` (1), `deploy-check` (2) |
| `app/api/tests/test_infra_files.py` | 1 | New. Section 6 |
| `docs/deploy/lightsail.md` | 1, 2 | New. The runbook |
| `app/docker-compose.prod.yml` | 2 | New. Section 3.6 |
| `app/deploy/deploy.sh` | 2 | New. Section 3.7 |
| `app/api/tests/test_deploy_files.py` | 2 | New. Section 6 |
| `CLAUDE.md` | 2 | One line: where infra and deploy live, and that the host is not public until OPS-04 |

## 6. Tests

All tests read files as text or parse them (PyYAML). `tofu show -json`
is **not** used: no network, no credentials, no AWS. No Docker.

`test_infra_files.py` (step 1):

| Test | Asserts |
|---|---|
| `test_only_ssh_is_opened` | `main.tf` has one `port_info` block, protocol `tcp`, `from_port` and `to_port` `22`, and no `80` or `443` |
| `test_ssh_cidr_has_no_default_and_rejects_open_world` | `ssh_allowed_cidrs` has no `default`, and its validation mentions `0.0.0.0/0` and `::/0` |
| `test_provider_is_pinned_and_lock_file_committed` | `versions.tf` pins an exact provider version and `.terraform.lock.hcl` exists |
| `test_no_secret_in_infra` | No `private_key`, `secret`, `token`, `password` assignment or `AKIA` string in `infra/tofu/` (the example file lists names only) |
| `test_cloud_init_hardens_ssh` | `cloud-init.yaml` disables password and root login and creates `/etc/odiservices` with mode `0700` |
| `test_state_files_are_ignored` | `.gitignore` covers `*.tfstate*`, `.terraform/` and `*.tfvars` |

`test_deploy_files.py` (step 2):

| Test | Asserts |
|---|---|
| `test_prod_override_keeps_lockdown` | Merged `api` and `web` keep `read_only`, `cap_drop: [ALL]` and `no-new-privileges:true` |
| `test_only_web_publishes_a_loopback_port` | `api` has no `ports`. `web` has one, starting `127.0.0.1:` |
| `test_restart_policy_is_unless_stopped` | Both services |
| `test_env_file_is_outside_the_repo` | `api` `env_file` is an absolute path under `/etc/` and no other file is listed |
| `test_no_secret_or_volume_in_prod_file` | No `SUPABASE`, `KEY`, `SECRET`, `TOKEN`, and no volume or bind mount |
| `test_deploy_script_is_safe` | Starts with `set -euo pipefail`, contains no `set -x`, no `printenv`, no `cat` of the env file |

## 7. Open questions

Answered by the owner on 2026-10-31: **OpenTofu** instead of a manual
runbook, region **`us-east-2`**, the **4 GB** plan, **local state** now and S3
later, **containers** (3.1), the **dual-stack** bundle, a **private repository**
reached through a read-only deploy key created by hand on the host (3.4), and
**owner-run checks 6 to 15** recorded in the final PR as a small exception to
the rule that only *Pending validation* checks may stay open. Still open, with
the recommendation applied unless the owner says otherwise:

1. **Where images are built.** On the host (no registry, no CI), or in a
   registry once CI exists. *Recommendation:* build on the host now.
2. **State later.** *Recommendation:* when the S3 item comes, add a bucket
   with versioning and encryption, use OpenTofu's native state locking, and
   migrate with `tofu init -migrate-state`. Nothing in this item blocks it.
