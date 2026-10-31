# Spec — OPS-02 docker-compose for local testing

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-02 |
| **Depends on** | OPS-01, BE-18 |
| **Spec status** | In review. Rewritten 2026-10-30 for the separate `api` and `web` images (OPS-01) |
| **Date** | 2026-10-30 |

## 1. Goal

One command runs the two images locally, the way they will run on the host, so
the owner can test the packaged setup before OPS-03. It never points at
production.

## 2. Scope

**In scope**

- `app/docker-compose.yml` with two services, `api` and `web`.
- `make compose-up` and `make compose-down`.
- Two lines in the "Docker" section of `app/README.md` (OPS-01 creates it).

**Out of scope**

- The images: OPS-01.
- Supabase, Access and Anthropic variables. Each item that adds a variable
  (BE-26, BE-23, BE-03) adds it to the model and to `.env.example`, and
  Compose passes it through with no change here (section 3.3).
- A local Supabase container. The owner's decision is a *dev Supabase
  project*, never production.
- Reverse proxy in front of `web`, TLS and Cloudflare: OPS-04. Deploy: OPS-03.

## 3. Design

### 3.1 The services

`app/docker-compose.yml`:

```yaml
# Local testing only. Point .env at the dev Supabase project, never production.
name: odiservices

services:
  api:
    build:
      context: api
    image: odiservices-api:local
    env_file:
      - path: .env
        required: false
    expose:
      - "8000"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    restart: "no"

  web:
    build:
      context: web
    image: odiservices-web:local
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "127.0.0.1:${PORTAL_HOST_PORT:-8000}:8080"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    restart: "no"
```

Rules:

- **Loopback only, through `web` only.** Only `web` publishes a port, on
  `127.0.0.1`, so the portal is not reachable from the network while there is
  no auth (BE-23). `api` has no `ports`: it is reachable from `web` on the
  Compose network and from nowhere else. The host port is `8000` unless
  `PORTAL_HOST_PORT` says otherwise.
- **Same images as the host.** Each service builds from its own Dockerfile
  and adds nothing. No bind mount of the source, no `command` override.
  Healthchecks come from the images.
- **`web` finds the API by name.** `API_UPSTREAM` keeps its default
  (`api:8000`), the service name and port.
- **Locked down.** Both have a read-only root filesystem, no capabilities and
  `no-new-privileges`. `nginx-unprivileged` writes only under `/tmp`. When
  BE-03 needs a scratch directory for an upload, that item adds a `tmpfs` or a
  volume to `api` and its spec says so.
- **No volume for data.** Statements and extracted output never persist on
  this machine through Compose: no `input/`, no `outputs/` mount
  (`CLAUDE.md`, "Security and data").
- **Restart.** `"no"`: this file is for testing, so a crash must be visible.
  OPS-03 chooses the policy on the host.

### 3.2 Environment

- `PORTAL_ENV` is **not** set by the file, so `api` runs as `prod` (BE-18's
  default). That is the point of the check: the packaged setup behaves like
  the host.
- Developers who want the dev behavior put `PORTAL_ENV=dev` in `app/.env`.
  Compose reads it through `env_file`. The dev bypass of BE-25 stays tied to
  that value.
- `app/.env` is optional (`required: false`). With none, `api` starts on
  defaults.
- Only `api` reads `.env`; `web` gets no `env_file`. `app/.env` is
  git-ignored and never enters an image: the `.dockerignore` files exclude it
  (OPS-01), and Compose injects it at run time only.

### 3.3 Supabase and the "never production" rule

`app/.env.example` gains no variable in this item. Later items add theirs
with a comment. For the Supabase ones (BE-26), the comment says they must
name the **dev** project. Until then:

- `docker-compose.yml` carries a comment at the top: *Local testing only.
  Point `.env` at the dev Supabase project, never production.*
- `app/README.md` repeats it in the Docker section.
- Nothing in the file mentions a project URL or a key.

Enforcement in code (refusing a production URL when `PORTAL_ENV` is not
`prod`) is a decision for BE-26, which owns the variables. See question 1.

### 3.4 Make targets

`app/Makefile`:

| Target | Runs |
|---|---|
| `compose-up` | `docker compose up --build --detach --wait` (waits for the healthcheck) |
| `compose-down` | `docker compose down --remove-orphans` |

`help` lists both. `--wait` makes `compose-up` fail when the container is not
healthy, which is the check in section 4.

## 4. Verification

Docker must be running. From `app/`:

| Check | Expected |
|---|---|
| `make compose-up` with no `.env` | Both images build, and the command returns once `api` and `web` are `healthy` |
| `docker compose ps` | Two services. `web` is `running (healthy)` with `127.0.0.1:8000->8080/tcp`. `api` is `running (healthy)` with no published port |
| `curl http://127.0.0.1:8000/healthz` | 200, `{"status":"ok"}` (through `web`, to `api`) |
| `curl -i http://127.0.0.1:8000/categorizer/abc-123` | 200, `text/html` |
| `curl -i http://127.0.0.1:8000/api/nope` | 404, the JSON `not_found` body |
| Only the web port is published: `lsof -nP -iTCP -sTCP:LISTEN` for the Docker ports | One listener, on `127.0.0.1:8000`, never `*` or `0.0.0.0`. Nothing on 8080 or on the API's port |
| `docker compose exec api id -u` and `docker compose exec web id -u` | `10001` and `101` |
| `docker compose exec api sh -c 'touch /app/x'` and the same in `web` with `/usr/share/nginx/html/x` | Both fail (read-only filesystem) |
| `PORTAL_HOST_PORT=8100 make compose-up` | The portal answers on `127.0.0.1:8100` |
| Optional `.env`: create `app/.env` with `PORTAL_LOG_LEVEL=DEBUG`, run `make compose-up` | `api`'s log level is `DEBUG` (the startup log line shows it). `web` has no such variable (`docker compose exec web env`). The script deletes the file afterwards |
| No image holds a `.env`: `docker compose exec api sh -c 'find /app -name ".env*"'`, and the same in `web` for `/usr/share/nginx/html`, while the file above exists on the host | Both print nothing |
| `docker compose logs` | `api` shows JSON `request` events (BE-21). Neither service logs a query string (request `/healthz?token=abc123` first, then search both logs for `abc123`) |
| `docker compose stop api`, then `curl -i http://127.0.0.1:8000/` | The page still returns 200. `/healthz` returns a 502 from nginx |
| `make compose-down` | The containers and the network are gone. `docker compose ps` is empty |

Each check runs when the item merges, with OPS-01 and BE-18 only. The checks
are run by hand, or by a script of the implementer's choice kept out of the
repo. The spec adds no script, because every command is one line.

## 5. Files

| File (in `app/`) | Change |
|---|---|
| `docker-compose.yml` | New. Section 3.1 |
| `Makefile` | `compose-up` and `compose-down` |
| `README.md` | Two lines in the Docker section |
| `api/tests/test_compose_file.py` | New. Section 6 |

## 6. Tests

`app/api/tests/test_compose_file.py` parses `app/docker-compose.yml` with
PyYAML (already a dependency of `uvicorn[standard]`; no new package). No
Docker, no network:

| Test | Asserts |
|---|---|
| `test_has_api_and_web_services` | `services` has only `api` and `web`, built from the contexts `api` and `web` |
| `test_only_web_publishes_a_port_on_loopback` | `api` has no `ports`. Every published port of `web` starts with `127.0.0.1:` |
| `test_env_file_is_optional_and_api_only` | `api` lists `.env` with `required: false`. `web` has no `env_file` |
| `test_no_secret_or_data_in_file` | The file text has no `SUPABASE`, `KEY`, `SECRET` or `TOKEN`, and no volume or bind mount at all |
| `test_containers_are_locked_down` | For both services: `read_only` is true, `cap_drop` has `ALL`, and `no-new-privileges:true` is set |
| `test_web_waits_for_a_healthy_api` | `web` depends on `api` with `condition: service_healthy` |

## 7. Open questions

1. **Guard against a production Supabase.** *Recommendation:* no code in
   this item. BE-26 decides how to tell the projects apart (for example a
   `PORTAL_SUPABASE_PROJECT` name that must match `PORTAL_ENV`).
2. **Default `PORTAL_ENV`.** Leaving it unset tests the packaged setup as
   production. *Recommendation:* keep that. Dev behavior is opt-in through
   `.env`.
3. **Dev profile with hot reload.** *Recommendation:* no. `make dev` already
   covers it, and a bind-mounted source would break the "same images as the
   host" rule.
4. **Read-only filesystem.** `api` may need a `tmpfs` entry once BE-03 handles
   uploads, and nginx may need more than `/tmp` (to be confirmed when the
   check runs). *Recommendation:* keep it now, and add what is proven needed.
