# Spec — OPS-04 Cloudflare Tunnel and Access in front of the portal

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-04 |
| **Depends on** | OPS-03, OPS-07 (the state of the new configuration goes in the OPS-07 bucket) |
| **Spec status** | Approved, 2026-11-02 (approved by the owner when #49 merged). Owner decisions of 2026-11-02 are applied: hostname `portal.tripleadev.com.br` with its DNS on Cloudflare; a Cloudflare Tunnel (the origin stays closed); Access allows the owner's company address and the domain `odisseiaviagens.com.br` (the address goes only in the git-ignored `terraform.tfvars`); the owner has no Cloudflare Zero Trust yet, so section 7 lists the steps; session length 12 hours; the recommendations of section 6 are accepted |
| **Date** | 2026-11-02 |

## 1. Goal

Make the portal reachable at `https://portal.tripleadev.com.br` for the people
the owner allows, and for nobody else, without opening a port on the host.
Today the only way in is an SSH tunnel from the owner's machine. After this
item, a browser reaches the `web` service through Cloudflare, Access asks for a
login first, and the origin cannot be reached except through the tunnel.

The owner opens the portal to the team only after there are features to
validate (BE-02 and later). Until then Access allows the owner's address and
the company domain, and the page is the landing placeholder.

## 2. Scope

**In scope**

- `infra/cloudflare/`: an OpenTofu configuration with its own state in the
  OPS-07 bucket (section 3.1). It creates the tunnel, its ingress rule, the
  DNS record, the Access application and the Access policy.
- `app/deploy/install-cloudflared.sh`: installs `cloudflared` on the host and
  runs it as a service (section 3.3).
- `docs/deploy/lightsail.md`: a Cloudflare section (how to reach the portal,
  how to rotate the token, how to take it offline).
- `make infra-check` covers the new directory. `test_infra_files.py` gains the
  tests of section 5.

**Out of scope**

- Verifying the Access JWT inside the API: that is BE-23. This item only
  prints the application's AUD and the team domain for it.
- Where secrets live on the host: OPS-05. This item puts one file there
  (`/etc/odiservices/cloudflared.env`, section 3.3) and OPS-05 may move it.
- Any change to `infra/tofu/` (the instance, its address, its firewall). The
  firewall already opens only port 22 and stays that way, and `user_data` is
  not touched, so the instance is not replaced.
- A Google login, service tokens for uptime monitors, more hostnames and a
  WAF policy (questions 3 and 4).

## 3. Design

### 3.1 The configuration (`infra/cloudflare/`)

| File | Content |
|---|---|
| `versions.tf` | `required_version >= 1.10.0`; `cloudflare/cloudflare` pinned to one exact version (chosen in step 1, section 8 assumption 1); the `aws` provider is not used; `.terraform.lock.hcl` committed |
| `backend.tf` | `backend "s3" {}`, partial, as in `infra/tofu/` |
| `backend.hcl.example` | `bucket = "odiservices-tofu-state-<account-id>"`, `key = "odiservices/cloudflare/terraform.tfstate"`, `region`, `encrypt = true`, `use_lockfile = true` |
| `variables.tf` | `account_id`, `zone_id`, `hostname` (default `portal.tripleadev.com.br`), `allowed_emails` (list), `allowed_email_domains` (list), `session_duration` (default `12h`). No default for the first four, so no id or address reaches the repository |
| `main.tf` | The resources of the next table |
| `outputs.tf` | `portal_url`, `team_domain`, `access_aud`, and `tunnel_token` (`sensitive = true`) |
| `terraform.tfvars.example` | The variable names with placeholders |

`terraform.tfvars` and `backend.hcl` stay git-ignored and are copied to
`~/odiservices-backups/`.

| Resource | Role |
|---|---|
| Tunnel (`cloudflare_zero_trust_tunnel_cloudflared`) | Remotely managed (`config_src = "cloudflare"`), named `odiservices-portal`. Its token comes from the data source `cloudflare_zero_trust_tunnel_cloudflared_token`, which feeds the sensitive output |
| Tunnel config | One ingress rule: `hostname` → `http://127.0.0.1:8080`, then `http_status:404` as the catch-all |
| Identity provider (`cloudflare_zero_trust_access_identity_provider`) | `type = "onetimepin"`, named `One-time PIN`. The account has none by default (step 1 found only the `cloudflare` method, for account members), so OpenTofu creates it |
| Access application | Self-hosted, domain `hostname`, session `session_duration`, `allowed_idps` is the one-time PIN provider only and `auto_redirect_to_identity = true`, so the login goes straight to the PIN |
| Access policy | Allow, `include` the emails and the email domains. Nothing else allows |
| DNS record | `portal` CNAME to `<tunnel-id>.cfargotunnel.com`, proxied. It `depends_on` the Access application and its policy, so the name never exists without Access in front |

Resource names are from the provider's v5 series. They are *assumed* until
`tofu validate` runs in step 1.

The only service the tunnel reaches is the `web` container on
`127.0.0.1:8080` (`app/docker-compose.prod.yml`). The `api` container has no
published port and stays that way: `/api` is reached through the nginx
`web` image, behind Access.

### 3.2 Identity and credentials

The owner creates a Cloudflare API token limited to the account and the zone
(section 7) and keeps it in `~/.config/odiservices/cloudflare.env`, mode 600,
as `CLOUDFLARE_API_TOKEN=...`. The agent runs `tofu` with that file loaded
(`set -a; . ~/.config/odiservices/cloudflare.env; set +a`) and never reads,
prints or commits it. The AWS side uses `AWS_PROFILE=odiservices-tofu` for the
state, as in OPS-07.

The tunnel token is a secret. It is in the state (a private, encrypted,
versioned bucket) and is read once with `tofu output -raw tunnel_token` by the
owner, who puts it on the host (section 3.3). It is never in the repository, a
log, a chat or an image. Rotating it is `tofu apply -replace` on the tunnel
secret, then the same copy.

### 3.3 The host

`app/deploy/install-cloudflared.sh`, run once by the owner over SSH:

1. Adds Cloudflare's apt repository and installs the `cloudflared` package.
2. Writes `/etc/odiservices/cloudflared.env` (root, `0600`) with
   `TUNNEL_TOKEN=` read from standard input, never from an argument or the
   shell history.
3. Writes `/etc/systemd/system/cloudflared.service`: `EnvironmentFile` that
   file, `ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run`,
   `Restart=always`, enabled at boot.
4. Starts it and waits for a registered connection.

The connection is outbound only (port 7844 to Cloudflare). The Lightsail
firewall is not changed.

### 3.4 Steps

| Step | Branch | Content |
|---|---|---|
| 1 | `feat/ops-04-step-1-skeleton` | A throwaway run of the whole loop, not committed: the owner's Cloudflare setup (section 7), a scratch configuration with hostname `portal-test.tripleadev.com.br` (tunnel, Access, DNS), `cloudflared` on the host, a browser login, then destroy (checks 4 to 11). The step's PR pins the provider version and records what the run showed in this spec |
| 2 | `feat/ops-04-step-2-config` | `infra/cloudflare/`, `make infra-check`, the tests, the real `portal` hostname applied (checks 1 to 3 and 12 to 14) |
| 3 | `feat/ops-04-step-3-host` | `install-cloudflared.sh`, the service on the host, the runbook, the closed-origin and reboot checks, OPS-04 set to Done (checks 15 to 19) |

Each stays under 500 changed lines. The feature branch is
`feature/ops-04-cloudflare`, and a final PR takes it to `main`.

## 4. Verification

The owner runs the rows marked *owner*. Each live check has a timeout of 120
seconds unless noted.

| # | Step | Check | Expected |
|---|---|---|---|
| 1 | 2 | `make infra-check` | Passes for `infra/tofu`, `infra/tofu-bootstrap` and `infra/cloudflare`, with no credentials |
| 2 | 2 | `test_infra_files.py` | Passes (section 5) |
| 3 | 2 | `git check-ignore infra/cloudflare/terraform.tfvars infra/cloudflare/backend.hcl` | Both are ignored |
| 4 | 1 | Preflight: `curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" https://api.cloudflare.com/client/v4/accounts/<account_id>/tokens/verify \| jq .result.status` (the token is account-owned, so the `/user/tokens/verify` endpoint answers "Invalid API Token") with the env file loaded, output not echoed beyond the status | `"active"` |
| 5 | 1 | *Owner:* `tofu plan` of the scratch configuration (agent asks "go") | Adds 1 tunnel, its config, 1 Access application, 1 policy, 1 identity provider and 1 DNS record; 0 to change, 0 to destroy |
| 6 | 1 | *Owner:* `tofu apply` of that saved plan (agent asks "apply") | Succeeds. This proves the token's permissions |
| 7 | 1 | On the host, the install steps of section 3.3, then `systemctl is-active cloudflared` and `journalctl -u cloudflared --no-pager \| grep -c "Registered tunnel connection"` (timeout 60 s) | `active`; 1 or more |
| 8 | 1 | `curl -sI https://portal-test.tripleadev.com.br/` | `302` with a `Location` on `cloudflareaccess.com`. The origin was not reached |
| 9 | 1 | *Owner:* open the test URL in a browser, log in with the one-time PIN sent to the owner's company address | The landing page loads |
| 10 | 1 | *Owner:* the same with an address outside the policy | Access refuses; the page never loads |
| 11 | 1 | *Owner:* `tofu destroy` of the scratch plan (agent asks "destroy"), after the service is stopped on the host (a tunnel with a live connector cannot be deleted), then `dig +short portal-test.tripleadev.com.br` and the tunnel list in the API | No DNS answer; no tunnel, Access application, policy or identity provider left. The service is stopped on the host and the env file removed |
| 12 | 2 | *Owner:* `tofu plan` in `infra/cloudflare` (agent asks "go") | Adds the 6 resources of section 3.1; 0 to change, 0 to destroy. The plan has no DNS record before the Access application |
| 13 | 2 | *Owner:* `tofu apply` of that saved plan (agent asks "apply"), then `tofu state list` | Succeeds; 6 resources |
| 14 | 2 | `curl -sI` on `https://portal.tripleadev.com.br/`, `/healthz` and `/api/` | Each answers `302` to `cloudflareaccess.com` (the host service is not yet installed, so the tunnel is down; Access still answers first) |
| 15 | 3 | *Owner:* `install-cloudflared.sh` on the host with the token on standard input; then `systemctl is-active cloudflared` and `systemctl is-enabled cloudflared` | `active`; `enabled` |
| 16 | 3 | `stat -c '%a %U' /etc/odiservices/cloudflared.env` on the host, and `git grep -n "TUNNEL_TOKEN" -- . ':!app/api/tests'` | `600 root`; only the variable name appears, no value |
| 17 | 3 | *Owner:* in a browser, `https://portal.tripleadev.com.br/` logged in as the owner, then `/healthz` | The landing page; `/healthz` returns `{"status":"ok"}` or the body the API defines |
| 18 | 3 | `nc -z -w 5 <public_ip> 8080`, `nc -z -w 5 <public_ip> 80`, `nc -z -w 5 <public_ip> 443`, and `aws lightsail get-instance-port-states --instance-name odiservices-portal` | The three connections fail; only port 22 is open |
| 19 | 3 | `sudo reboot` on the host (timeout 180 s), wait for SSH, then `systemctl is-active cloudflared` and check 17 again | `active`, and the portal answers after the owner's login |

The one check that stays with the owner at the end is who is let in: the
policy lists the owner's address and the company domain, and nobody else (check
10 and the policy in the Cloudflare dashboard).

## 5. Tests

`app/api/tests/test_infra_files.py` reads the files and asserts, with no
Cloudflare call and no fixture beyond the repository files:

| Test | Asserts |
|---|---|
| `test_cloudflare_dns_depends_on_access` | The DNS record declares `depends_on` for the Access application and its policy |
| `test_cloudflare_has_no_identifier_defaults` | `account_id`, `zone_id`, `allowed_emails` and `allowed_email_domains` have no default, and the example holds placeholders only |
| `test_cloudflare_provider_is_pinned` | The provider version is one exact version and `.terraform.lock.hcl` is committed |
| `test_cloudflare_token_is_sensitive` | The `tunnel_token` output is `sensitive = true` and no file under `infra/cloudflare/` has a literal token |
| `test_ingress_reaches_web_only` | The ingress rule targets `127.0.0.1:8080` and ends with `http_status:404` |
| `test_firewall_opens_only_ssh` | `infra/tofu/main.tf` still opens port 22 and no other port |
| `test_install_script_keeps_token_private` | The script reads the token from standard input, writes the env file with mode `0600` and sets `EnvironmentFile` |

## 6. Open questions

1. **Where the tunnel token lives.** Recommended: in the encrypted state and
   copied to the host by the owner. The alternative is to create the tunnel in
   the dashboard and keep it out of OpenTofu, which loses the record in code.
2. **Session length.** Decided by the owner on 2026-11-02: 12 hours, then one-time PIN again.
3. **Login method.** Recommended: one-time PIN now, because it works for any
   address in the policy with no setup. A Google login can be added when the
   team grows, in its own item.
4. **`/healthz` behind Access.** Recommended: yes. The host's own health check
   is local. A future external monitor needs an Access service token, decided
   with OPS-05.
5. **The portal is on the internet behind Access before BE-23.** The API does
   not yet check the JWT itself. Recommended: accept it, because only the
   owner and the company domain pass Access, the tunnel is the only way in and
   BE-23 follows. The owner opens the portal to the team after features exist.

## 7. Prerequisites

**Owner steps (none done yet)**

1. **A Cloudflare account** at `dash.cloudflare.com` with the zone
   `tripleadev.com.br` active (its name servers point to Cloudflare). Check:
   the zone's status reads *Active*.
2. **Zero Trust.** Open *Zero Trust* in the dashboard, choose the **Free**
   plan (up to 50 users; Cloudflare asks for a payment method but charges
   nothing), and choose a team name, for example `tripleadev`. The team
   domain becomes `<team>.cloudflareaccess.com`.
3. **The login method.** Nothing to do: the account has no One-time PIN
   provider, and OpenTofu creates it (section 3.1).
4. **An API token** (*My Profile › API Tokens › Create Token › Custom*), with:
   - Account › **Cloudflare Tunnel**: Write
   - Account › **Access: Apps**: Write
   - Account › **Access: Policies**: Write
   - Account › **Access: Organizations, Identity Providers, and Groups**: **Write** (the provider is created by OpenTofu; Read is not enough)
   - Zone › **DNS**: Write

   These are the labels the dashboard showed on 2026-11-02 (it splits Apps and
   Policies and says Write for what older docs call Edit). Not the legacy
   "Argo Tunnel" permission.
   - Account resources: only this account. Zone resources: only
     `tripleadev.com.br`. No expiry shorter than the project needs; no IP
     filter unless the owner's address is fixed.
5. **Keep it local:** `mkdir -p ~/.config/odiservices`, then create
   `~/.config/odiservices/cloudflare.env` with `CLOUDFLARE_API_TOKEN=<token>`
   and `chmod 600` it. Never paste the token in a chat.
6. **Two identifiers** (not secret): the *account id* (right side of the
   dashboard's account home) and the *zone id* (the zone's overview page). They
   go in the git-ignored `terraform.tfvars` and in `~/odiservices-backups/`.

| Prerequisite | Provider | Preflight | Expected |
|---|---|---|---|
| OpenTofu with `use_lockfile` | agent | `tofu version` | `v1.13.2` or newer. **Green** (2026-11-02) |
| The state bucket and the AWS profile | agent | `AWS_PROFILE=odiservices-tofu aws sts get-caller-identity` | `…:user/odiservices-tofu` |
| A Cloudflare account with the zone active, Zero Trust on the Free plan | owner | The dashboard (steps 1 and 2) | Zone *Active*; team domain set. **Missing** |
| The API token, scoped, in `~/.config/odiservices/cloudflare.env` | owner | Check 4 (the account endpoint) | `"active"`. **Green** (2026-11-02) |
| `portal` and `portal-test` are free in the zone | agent | `dig +short portal.tripleadev.com.br` and `portal-test.tripleadev.com.br` | No answer. Not checked yet |
| Inventory | owner | The zone's DNS page and Zero Trust apps list | Assumed empty of `portal` records and Access apps. The token may not list them, so the owner confirms |
| SSH to the host | owner | `ssh deploy@<public_ip> true` | Exit 0. Green since OPS-03 |
| Cost | | Tunnel and Access on the Free plan, up to 50 users | US$0 a month. The host stays near US$24. A failed attempt costs nothing. The owner destroys a leftover tunnel with `tofu destroy` |

Packages: `cloudflared` on the host, from Cloudflare's apt repository
(authorized by this spec); the `cloudflare/cloudflare` provider, downloaded by
`tofu init`. Nothing is installed on the owner's machine. `dig` and `nc` are
already there.

## 8. Assumptions to verify

1. **The Cloudflare provider's v5 resource names** in section 3.1. *Assumed.*
   `tofu validate` in step 1 proves them, and the same step pins the exact
   version.
2. **The Free plan covers Tunnel and Access for this use.** *Assumed* from
   Cloudflare's documentation. Step 1 applies on the owner's account.
3. **One-time PIN is available after the Zero Trust setup.** *Wrong, corrected
   in step 1 (2026-11-02).* The account listed only the `cloudflare` method
   and check 9 showed "restricted to members of the account". The provider is
   now a resource (section 3.1) and the token needs Write on identity providers.
4. **Universal SSL covers `portal.tripleadev.com.br`.** *Assumed*: a
   first-level subdomain of a zone on Cloudflare. Check 8 gets a valid TLS
   answer or fails visibly.
5. **`cloudflared` installs from the apt repository on the host's Ubuntu and
   runs with `TUNNEL_TOKEN` from an `EnvironmentFile`.** *Assumed.* Check 7.
6. **The host may connect outbound to Cloudflare on port 7844.** *Assumed*:
   Lightsail does not restrict outbound traffic. Check 7.
7. **Access answers before the origin.** *Assumed.* Check 8: a request with no
   login gets a `302` and never reaches nginx.
8. **The OPS-07 bucket policy covers a second key.** *Assumed*: the policy is
   on the bucket, not on one key. Step 2's first `init` proves it.
9. **The `odiservices-tofu` S3 access is separate from the Cloudflare token.**
   *Verified* by design: two providers in two configurations, no shared
   credential.
10. **The v5 provider (5.28.1) names and shapes in section 3.1.** *Verified* in
    step 1: the resources apply and the token comes from the data source.
11. **The tunnel config cannot be destroyed by OpenTofu** (the plan warns).
    *Verified*: it is removed with its tunnel, and nothing is left.
12. **A tunnel with a connected `cloudflared` cannot be destroyed.** *Found in
    step 1* (the first `destroy` failed on the tunnel). Stop and remove the
    service on the host first; the runbook says so.
13. **Outside addresses get no PIN.** *Verified* (check 10): the PIN never
    arrived for an address outside the policy.

## 9. Approvals

| Action | Who | Standing answer |
|---|---|---|
| Create the Cloudflare account, enable Zero Trust, create the API token | Owner | The agent never does these (section 7) |
| `tofu plan` (scratch, real) | Owner says "go" | One saved plan each |
| `tofu apply` of a saved plan | Owner says "apply" | One saved plan |
| `tofu destroy` of the scratch configuration | Owner says "destroy" | Once, after check 10 |
| Install `cloudflared` and write the token on the host | Owner runs the script | The agent writes the script and does not run it with the token |
| Reboot the host (check 19) | Owner says "go" | Once |
| Open the portal to people beyond the policy | Owner | Not in this item |
| Destroy the real configuration | Owner | Never in this item |
