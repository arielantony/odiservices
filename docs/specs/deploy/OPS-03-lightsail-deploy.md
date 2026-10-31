# Spec — OPS-03 Deploy to AWS Lightsail

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-03 |
| **Depends on** | OPS-01, OPS-02, BE-32 |
| **Spec status** | Draft, awaiting the owner's answers to section 7 |
| **Date** | 2026-10-31 |

## 1. Goal

Run the two images (OPS-01) on one Lightsail instance, started by Compose and
restarted by Docker, so the owner can reach the portal over an SSH tunnel and
test the real host. The instance is **not** public yet: Cloudflare and Access
come in OPS-04, and the portal has no auth until BE-23. Until then nothing
listens on a public port.

## 2. Scope

**In scope**

- `app/docker-compose.prod.yml`, an override of `docker-compose.yml` (OPS-02)
  for the host: restart policy, the env file path, the image tags.
- `app/deploy/deploy.sh`, run **on the host**: update the checkout, build,
  restart, wait for health, roll back on failure.
- `docs/deploy/lightsail.md`, the runbook: create the instance, firewall,
  Docker install, first deploy, update, rollback, reach the portal.
- `make deploy-check`, a local lint of the two deploy files (section 6).

**Out of scope**

- Cloudflare, Tunnel, Access and the firewall that restricts the origin to
  Cloudflare: OPS-04.
- How secrets are created, rotated and stored: OPS-05. This item only names
  the file the host reads (3.3).
- A registry, CI and automatic deploys: not in the backlog. The host builds
  the images itself (question 2).
- Backups of data: nothing persists on the host (no volume, no `input/`, no
  `outputs/`).
- Terraform or any infrastructure as code. The runbook is manual (question 5).

## 3. Design

### 3.1 Container, not systemd

The previous Lightsail setup ran the app under systemd. This item uses
Compose, because the unit of delivery is already two images with a read-only
root, dropped capabilities and a healthcheck (OPS-01, OPS-02). A systemd unit
would need Python, Node and nginx installed and pinned on the host, and
the "same image as local" guarantee would be lost. Docker's
`restart: unless-stopped` brings the stack back after a crash or a reboot,
as long as the Docker service is enabled at boot.

### 3.2 The host

| Item | Choice |
|---|---|
| Blueprint | Ubuntu LTS, Lightsail |
| Size | 2 GB RAM or more (the web image build runs `yarn build`; 1 GB can run out of memory) |
| Region | Question 4 |
| Firewall (Lightsail networking) | **Only TCP 22.** No 80, no 443. Section 3.4 explains how to reach the portal |
| SSH | Key only. Password login off. Allow-list the owner's IP in the Lightsail firewall if the address is stable |
| Docker | Docker Engine and the Compose plugin from Docker's apt repository, enabled at boot |
| Unattended upgrades | On, security updates only |

### 3.3 Files on the host

- `/opt/odiservices`: a checkout of this repository at a tag or a commit,
  read by the deploy user. It holds no data.
- `/etc/odiservices/.env`: owned by `root`, mode `0600`. The prod override
  points `env_file` at it. OPS-05 decides its contents and rotation. Until
  OPS-05 lands, the file may be empty and `api` starts on defaults (`prod`).
- The file is **never** in the checkout, the image, a log or a PR.

### 3.4 Reaching the portal before OPS-04

`web` publishes `127.0.0.1:8080` on the host, as in OPS-02. The owner opens
`ssh -L 8080:127.0.0.1:8080 <host>` and browses `http://127.0.0.1:8080`. There
is no public listener, so the missing auth (BE-23) exposes nothing. OPS-04
replaces this with a Cloudflare Tunnel and does not change the images.

### 3.5 `docker-compose.prod.yml`

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

### 3.6 `deploy.sh`

Run as the deploy user, from `/opt/odiservices/app`, with a git ref argument:

1. `git fetch` and check out the ref. Refuse a dirty checkout.
2. Record the tag of the running images (`previous`).
3. Build both images, tagged `odiservices-<svc>:<short sha>`.
4. `DEPLOY_TAG=<short sha> docker compose ... up --detach --wait`.
5. Check `curl -fsS http://127.0.0.1:8080/healthz` and the page `/`.
6. On any failure, `up` again with `previous` and exit non-zero.
7. Remove images older than the last three.

The script prints no environment variable, no env file content and no request
data.

## 4. Verification

The checks need an AWS account and a Lightsail instance, so **the owner runs
them with the implementer present**, on a throwaway instance created from the
runbook. The result is recorded in the PR as "validated on <date>", with no
addresses or keys. Checks 1 to 3 need only this repository.

| # | Check | Expected |
|---|---|---|
| 1 | `make deploy-check` | Passes (section 6) |
| 2 | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` locally with a dummy `/etc/odiservices/.env` path replaced by a temp file | Valid. `api` has no `ports`. `web` publishes only `127.0.0.1:8080`. Both have `restart: unless-stopped`, `read_only`, `cap_drop: [ALL]` |
| 3 | `shellcheck app/deploy/deploy.sh` | No findings |
| 4 | Follow `docs/deploy/lightsail.md` on a fresh instance up to the first deploy | `deploy.sh <ref>` ends with both containers `healthy` |
| 5 | From the owner's machine, scan the instance's public IP (`nmap -Pn -p 1-65535` or the equivalent) | Only 22 is open |
| 6 | `ssh -L` tunnel, then `curl` `/healthz`, `/` and `/api/nope` on the forwarded port | 200 `ok`, 200 HTML, 404 `not_found` JSON. The CSP headers of BE-32 are present |
| 7 | `sudo reboot`, wait, repeat check 6 | The stack came back with no manual step |
| 8 | `docker kill` the `api` container | Docker restarts it and `/healthz` recovers |
| 9 | Deploy a ref whose `web` healthcheck fails (a deliberately broken commit on a scratch branch) | `deploy.sh` exits non-zero and the previous tag is serving again |
| 10 | `stat -c '%U %a' /etc/odiservices/.env`, then `docker compose exec api sh -c 'find /app -name ".env*"'` | `root 600`. Nothing found in the container |
| 11 | `docker compose logs`, search for a query string sent with `/healthz?token=abc123` | Not found (BE-21) |

The throwaway instance is deleted after the checks.

## 5. Files

| File | Change |
|---|---|
| `app/docker-compose.prod.yml` | New. Section 3.5 |
| `app/deploy/deploy.sh` | New. Section 3.6 |
| `docs/deploy/lightsail.md` | New. The runbook |
| `app/Makefile` | `deploy-check` |
| `app/api/tests/test_deploy_files.py` | New. Section 6 |
| `CLAUDE.md` | One line: where deploy lives and that the host is not public until OPS-04 |

## 6. Tests

`test_deploy_files.py` merges the two Compose files with PyYAML and reads
`deploy.sh` as text. No Docker, no network. `make deploy-check` runs it and
`shellcheck` when installed.

| Test | Asserts |
|---|---|
| `test_prod_override_keeps_lockdown` | Merged `api` and `web` keep `read_only`, `cap_drop: [ALL]` and `no-new-privileges:true` |
| `test_only_web_publishes_a_loopback_port` | `api` has no `ports`. `web` has one, starting `127.0.0.1:` |
| `test_restart_policy_is_unless_stopped` | Both services |
| `test_env_file_is_outside_the_repo` | `api` `env_file` is an absolute path under `/etc/` and no other file is listed |
| `test_no_secret_or_volume_in_prod_file` | No `SUPABASE`, `KEY`, `SECRET`, `TOKEN`, and no volume or bind mount |
| `test_deploy_script_is_safe` | Starts with `set -euo pipefail`, contains no `set -x`, no `printenv`, no `cat` of the env file |

## 7. Open questions

1. **Container or systemd.** *Recommendation:* containers (3.1).
2. **Where images are built.** On the host (no registry, no CI, one more
   moving part avoided), or in a registry (ECR or GHCR) once CI exists.
   *Recommendation:* build on the host now. Revisit when CI is in the backlog.
3. **Instance size.** *Recommendation:* the 2 GB plan. Lower only if the build
   moves off the host.
4. **Region.** *Recommendation:* `sa-east-1` (São Paulo) for latency to the
   finance team. Tell me if data residency or price says otherwise.
5. **Manual runbook or Terraform.** *Recommendation:* manual runbook. There is
   one instance, and the cost of IaC is not paid back yet.
6. **Verification by the owner.** Checks 4 to 11 need the owner's AWS account.
   *Recommendation:* accept them as owner-run checks recorded in the PR, since
   no one else can run them. This is a small exception to the rule that only
   *Pending validation* checks may stay open, so the owner must approve it.
7. **Deploy user and SSH.** *Recommendation:* a non-root `deploy` user in the
   `docker` group. Be aware that this group is root-equivalent, so only
   the owner's key goes on that account.
