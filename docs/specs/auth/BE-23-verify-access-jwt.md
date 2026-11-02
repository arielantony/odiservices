# Spec — BE-23 Verify the Cloudflare Access JWT on every protected request

| | |
|---|---|
| **Backlog** | Platform › Authentication › BE-23 |
| **Depends on** | BE-17, BE-18, BE-20, BE-21, OPS-03, OPS-04 (the live checks need the portal behind Access) |
| **Spec status** | In review, 2026-11-02 |
| **Date** | 2026-11-02 |

## 1. Goal

The API accepts a request to a protected route only when it carries a valid
token that Cloudflare Access signed for this application. Today Access guards
the portal at the edge only. After this item the API checks the token itself,
so a request that reaches the API without passing through Access (an SSH
tunnel, a process on the host, an Access policy removed by mistake) gets a
401. The verified identity (`sub` and `email`) is available to later items:
BE-24 turns it into a `users` row, and BE-02 is the first endpoint that
returns data.

## 2. Scope

**In scope**

- `server/access.py`: the verifier and the FastAPI dependency.
- Two settings, `PORTAL_ACCESS_TEAM_DOMAIN` and `PORTAL_ACCESS_AUD`.
- Deny by default: every route needs a valid token except an explicit list
  that holds `/healthz` only.
- `GET /api/session`: a route that answers `{"authenticated": true}` to a
  valid token. It carries no data and no email. It exists so the item can be
  checked live, and so FE-19 can detect an expired session.
- The runbook step that puts the two values on the host.

**Out of scope**

- The `users` row and the email shown in the interface: BE-24.
- The local development bypass: BE-25. Until it exists, a local run has no
  way past the check, which is the safe side.
- Pages and static files: nginx serves them, and they carry no data
  (`docs/BACKEND_GUIDELINES.md`, Auth). Only the API is checked.
- `/docs` and `/openapi.json`: nginx does not proxy them, and BE-22 decides
  how to publish them.
- Rate limiting and blocking by email: Access owns the allow list.

## 3. Design

### 3.1 What is verified

Access adds the header `Cf-Access-Jwt-Assertion` to every request it lets
through. The API reads only this header. It ignores the `CF_Authorization`
cookie and `Authorization`, so there is one place to look and one place to
get wrong.

The token must satisfy all of these, or the request gets a 401:

| Rule | Value |
|---|---|
| Algorithm | `RS256` only. `none` and `HS256` are rejected, which closes algorithm confusion |
| Signature | Checked against the key whose `kid` the token names. A token without `kid` is rejected |
| Issuer | `https://<PORTAL_ACCESS_TEAM_DOMAIN>` |
| Audience | `PORTAL_ACCESS_AUD`. Access sends `aud` as a list, so the audience matches when it is in the list |
| Time | `exp` is required, `nbf` is checked, with 60 seconds of clock tolerance |
| Subject | `sub` must be a non-empty string. `email`, when present, must be a string |

The keys come from `https://<team domain>/cdn-cgi/access/certs`. They are
cached in memory for 5 minutes and refetched once when a token names an
unknown `kid` (Access rotates its keys). The fetch has a 5 second timeout.

### 3.2 Answers

Every refusal is JSON in the shape the API already uses
(`{"error": {"code", "message"}}`), with `Cache-Control: no-store`. The
message is in pt-BR because the interface shows it. It never says which rule
failed.

| Case | Status | `code` | `message` |
|---|---|---|---|
| No header, or the token fails a rule of 3.1 | 401 | `unauthorized` | "Sessão inválida ou expirada. Entre novamente." |
| The keys cannot be fetched and no cached key matches, or the two settings are not set | 503 | `auth_unavailable` | "Não foi possível verificar sua sessão. Tente novamente." |

Fail closed: no case lets a request through.

The token, the claims, the email and the keys are never logged. The request
log already records the status and the route (BE-21). A 401 or 503 appears
there as a `WARNING` or an `ERROR`, which is enough to notice.

### 3.3 Settings (BE-18 pattern, both added to `.env.example`)

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `PORTAL_ACCESS_TEAM_DOMAIN` | string, `^[a-z0-9-]+\.cloudflareaccess\.com$` | unset | Team domain of the Access application |
| `PORTAL_ACCESS_AUD` | string, 64 hexadecimal characters | unset | AUD tag of the Access application (`tofu output -raw access_aud` in `infra/cloudflare/`) |

- Neither is a secret, so they are plain strings.
- Set one without the other, or set a malformed value: startup fails, and
  the error names the variable and never prints its value (BE-18).
- **Neither set: the server still starts**, and every protected route answers
  503. `/healthz` stays up, so the existing container and deploy checks
  (OPS-01 to OPS-03), which run without these variables, keep passing. The
  server logs one `WARNING` line at startup, `access_not_configured`.
- The domain pattern keeps a mistyped setting from pointing the key lookup at
  another host.

### 3.4 Where the check runs

`create_app()` takes an optional `access_verifier` (tests pass one that uses
a local key set; production builds the real one from the settings). The check
is a dependency applied to the whole application, and the explicit list of
exempt routes is a constant in `access.py`:

```python
PUBLIC_ROUTES = frozenset({"/healthz"})
```

A router added later is protected without anyone remembering to protect it.
A test enumerates `app.routes` and fails if a route that is not in the list
answers anything but 401 without a token.

The dependency is a plain `def`, so FastAPI runs it in its thread pool and
the key fetch does not block the event loop. It returns
`AccessIdentity(subject, email)`, a frozen dataclass. BE-24 reads it.

### 3.5 Files

| File | Change |
|---|---|
| `app/api/server/access.py` | New: `AccessIdentity`, `AccessVerifier`, the two exceptions, `require_access`, `PUBLIC_ROUTES` |
| `app/api/server/routes/session.py` | New: `GET /api/session` |
| `app/api/server/settings.py` | The two fields and the both-or-none rule |
| `app/api/server/main.py` | Build the verifier, add the application-wide dependency, include the session router |
| `app/api/requirements.in` and `requirements.txt` | Add `pyjwt[crypto]`, recompiled with `uv pip compile` (section 7) |
| `app/.env.example` | The two names, with a comment each |
| `docs/deploy/lightsail.md` | Subsection: put the two values in `/etc/odiservices/.env` and redeploy |
| `docs/BACKEND_GUIDELINES.md` | Auth section: the check is in place, the two settings, the exempt list |
| `docs/BACKLOG.md` | BE-23 status; the Authentication › Backend area moves to Planned |

The change is one pull request, about 450 changed lines with the tests. If
it passes 500 while it is written, it splits at the seam between the
verifier (settings, `access.py`, their tests) and the application wiring
(`main.py`, `session.py`, the runbook), and this spec is amended first.

## 4. Verification

Every check runs when the item merges. The owner runs the ones marked
*Owner*, because they need the host or the browser.

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`: `make test-api` | All tests pass, including the ones in section 5 |
| 2 | From `app/`: `PORTAL_ACCESS_TEAM_DOMAIN=example.cloudflareaccess.com PORTAL_ACCESS_AUD=$(printf '0%.0s' {1..64}) make serve`, then `curl -si http://127.0.0.1:8000/api/session` | `401`, the JSON error of 3.2, `Cache-Control: no-store` |
| 3 | The same server: `curl -si http://127.0.0.1:8000/healthz` and `curl -si -H 'Cf-Access-Jwt-Assertion: aaa.bbb.ccc' http://127.0.0.1:8000/api/session` | `200` for `/healthz`, `401` for the forged token |
| 4 | `PORTAL_ACCESS_AUD=xyz make serve` | Startup fails and the message names `PORTAL_ACCESS_AUD` and does not print `xyz` |
| 5 | With neither variable set: `make serve`, then `curl -si http://127.0.0.1:8000/api/session` and `/healthz` | `503` with `auth_unavailable`, and `200` for `/healthz` |
| 6 | *Owner:* put the two values in `/etc/odiservices/.env` on the host and run `deploy.sh` (runbook, new subsection) | The script ends with `deployed <sha>` |
| 7 | *Owner:* on the host, `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/session`, then the same with `-H 'Cf-Access-Jwt-Assertion: aaa.bbb.ccc'` | `401` twice: the origin refuses a request that did not come through Access |
| 8 | *Owner:* in the browser, log in at `https://portal.tripleadev.com.br` and open `/api/session` | `{"authenticated":true}`: a real token passes (algorithm, issuer, audience and `sub` match) |
| 9 | *Owner:* on the host, `sudo docker logs $(sudo docker ps -q --filter name=api) 2>&1 \| grep -c 'eyJ'` | `0`: no token reached the log |
| 10 | `git grep -n 'eyJ' -- . ':!app/api/tests'` and `git grep -n 'cloudflareaccess.com' -- app/api/server` | No match for the first. The second shows only the pattern in `settings.py` |

Check 8 is the one that proves the design against the real service, so the
item is not Done without it.

## 5. Tests

`app/api/tests/`. Tests never call Cloudflare. A helper in
`tests/access_helpers.py` generates an RSA key pair at run time, signs
tokens with it and serves its public key through a fake key client. No key
and no token is stored in the repository. Emails and subjects are obviously
fictitious (`fulano@exemplo.com`, `sub-fulano`).

`test_access_verifier.py`

| Test | Asserts |
|---|---|
| `test_valid_token_returns_identity` | `subject` and `email` come from the claims |
| `test_audience_as_list_matches` | `aud` is a list that holds the application's AUD: accepted |
| `test_wrong_audience_rejected` | Another AUD: invalid |
| `test_wrong_issuer_rejected` | Another team domain in `iss`: invalid |
| `test_expired_token_rejected` | `exp` in the past by more than 60 s: invalid |
| `test_clock_tolerance` | `exp` 30 s in the past: accepted. `nbf` 30 s in the future: accepted. 120 s: invalid |
| `test_missing_exp_rejected` | A token with no `exp`: invalid |
| `test_missing_or_empty_subject_rejected` | No `sub`, or an empty one: invalid |
| `test_email_must_be_string` | `email` that is not a string: invalid |
| `test_signed_with_other_key_rejected` | A valid shape signed by another key: invalid |
| `test_none_algorithm_rejected` | An unsigned token with `alg: none`: invalid |
| `test_hs256_with_public_key_rejected` | A token signed with HS256 using the public key as the secret: invalid |
| `test_missing_kid_rejected` | A token without `kid`: invalid |
| `test_garbage_rejected` | `""`, `"abc"` and `"a.b.c"`: invalid, with no exception escaping |
| `test_key_fetch_failure_is_unavailable` | The fake client raises a network error: `AccessUnavailable`, not invalid |

`test_access_routes.py`

| Test | Asserts |
|---|---|
| `test_no_header_is_401` | Status, JSON body, `Cache-Control: no-store` |
| `test_valid_token_is_200` | `GET /api/session` answers `{"authenticated": true}` and the body has no email |
| `test_invalid_token_is_401` | A forged token: 401 with the same body as a missing one |
| `test_only_the_access_header_counts` | A valid token in the `CF_Authorization` cookie or in `Authorization: Bearer` is ignored: 401 |
| `test_healthz_is_public` | `/healthz` answers 200 with no header |
| `test_every_route_is_protected_except_the_list` | Enumerates the `APIRoute` entries of `app.routes`; each one outside `PUBLIC_ROUTES` answers 401 without a token |
| `test_keys_unavailable_is_503` | The fake client fails: 503, `auth_unavailable` |
| `test_not_configured_is_503_and_healthz_ok` | No settings: protected route 503, `/healthz` 200, one `access_not_configured` warning at startup |
| `test_token_and_email_never_logged` | After 200, 401 and 503 requests, `capsys` output holds no part of the token and no `@` |

`test_settings.py` (additions)

| Test | Asserts |
|---|---|
| `test_access_settings_optional` | Neither set: `Settings()` builds, both fields are `None` |
| `test_access_settings_both_or_none` | Only one set: startup error that names the variable that is missing |
| `test_access_team_domain_pattern` | `evil.example.com` and `tripleadev.cloudflareaccess.com.evil.com` are refused, naming `PORTAL_ACCESS_TEAM_DOMAIN` |
| `test_access_aud_pattern` | A value that is not 64 hexadecimal characters is refused, and the error does not print it |

## 6. Open questions

| # | Question | Recommended |
|---|---|---|
| 1 | Which library verifies the token? | **PyJWT with `cryptography`** (`pyjwt[crypto]`): small, maintained, and it ships a key-set client that caches and refetches on an unknown `kid`. `authlib` and `joserfc` do more than we need |
| 2 | Status when the keys cannot be fetched or the settings are not set | **503**, so the interface can tell "sign in again" from "try later". The TypeScript reference made the same split. A 401 for both is the alternative |
| 3 | Add `GET /api/session` in this item? | **Yes.** There is no other protected route until BE-02, so without it check 8 cannot run, and FE-19 needs a way to ask "is my session alive?" |
| 4 | Fail at startup when `PORTAL_ENV=prod` and the settings are missing? | **No.** It would break the container and deploy checks that start the server with no variables. A 503 with a startup warning fails closed and keeps `/healthz` up |
| 5 | Log the reason for a refusal (expired, wrong audience)? | **No.** The status in the request log is enough for now. A reason adds a log field to design, and an expired session is not an incident |

A question with no answer becomes an assumption with the recommended option.

## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| The portal is behind Access (OPS-04 Done) | Agent | `curl -sI https://portal.tripleadev.com.br/healthz \| head -1` | `HTTP/2 302` |
| The key set is published | Agent | `curl -s https://tripleadev.cloudflareaccess.com/cdn-cgi/access/certs \| python3 -c 'import json,sys; print(len(json.load(sys.stdin)["keys"]))'` | A number of 1 or more |
| The AUD is known | Owner or agent, with the Cloudflare token loaded as in the runbook | From `infra/cloudflare/`: `tofu output -raw access_aud \| wc -c` | `65` (64 characters and a newline). The value is not secret, and it stays out of the repository |
| SSH access to the host | Owner | `ssh -i <SSH_KEY_FILE> deploy@<public_ip> true; echo $?` | `0` |
| A way to edit `/etc/odiservices/.env` | Owner | `ssh -t -i <SSH_KEY_FILE> deploy@<public_ip> 'sudo -n true' ; echo $?` | `0`, or the owner uses `sudo` in a terminal |
| A package that resolves for Python 3.14 | Agent | `printf 'pyjwt[crypto]\n' > "$SCRATCH/in.txt" && uv pip compile --python-version 3.14 "$SCRATCH/in.txt"` | Pins `pyjwt`, `cryptography`, `cffi`, `pycparser` |

**Packages this item installs** (and only these):
`pyjwt[crypto]`, which pulls `cryptography`, `cffi` and `pycparser`, all
pinned by `uv pip compile` in `requirements.txt`. The `cryptography` package
is already needed by the test helper, so it is a runtime dependency, not a
test-only one.

**Actions that need the owner's explicit OK.** Approving this spec is the
standing OK for the package above and for opening the pull request. The host
edit (check 6) and the deploy are the owner's own commands. The agent never
reads `/etc/odiservices/.env` and never uses the owner's SSH key.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | nginx forwards `Cf-Access-Jwt-Assertion` to the API | *Verified* by reading `web/nginx/default.conf.template`: `proxy_set_header` sets only `Host`, and nginx passes the other request headers | Check 8 |
| 2 | Access sends the token to the origin through the tunnel in that header | *Assumed* (documented Access behavior; the TypeScript reference used it) | Check 8 |
| 3 | The token has `alg` RS256, `iss` `https://<team domain>`, `aud` as a list, a `sub` and an `email` | *Assumed*. The reference checked `iss`, `aud` and RS256, but `sub` is new here | Check 8. If a real token lacks `sub`, the check shows a 401 and this spec is amended before the code goes on |
| 4 | `PyJWKClient` caches the key set and refetches once on an unknown `kid` | *Assumed* | A smoke run in the first commit: a local HTTP server that serves a key set, asked for a known `kid`, then for a rotated one |
| 5 | `cryptography` has a wheel for Python 3.14 on macOS arm64 and on the Linux image | *Assumed* | `make setup-api` and `make build-api-image` (the image build is part of `make test` or the Dockerfile check) in the first commit |
| 6 | The `api` container (read-only filesystem) can reach `https://<team domain>` | *Assumed* | Check 8. If it fails, the key fetch needs egress or a cache directory, and this spec is amended |
| 7 | `PyJWKClient` writes nothing to disk | *Assumed* | Check 8 on the read-only container |

Assumptions 4 and 5 are cheap and run first, before anything is built on
them. Assumptions 2, 3, 6 and 7 can only be seen with the real service, so
check 8 stays in the item and the item is not Done until it passes.
