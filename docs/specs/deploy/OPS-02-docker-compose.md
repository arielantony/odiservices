# Spec — OPS-02 docker-compose for local testing

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-02 |
| **Depends on** | OPS-01, BE-18 |
| **Spec status** | In review |
| **Date** | 2026-10-30 |

## 1. Goal

One command runs the portal image locally, the way it will run on the host,
so the owner can test the packaged setup before OPS-03. It never points at
production.

## 2. Scope

**In scope**

- `app/docker-compose.yml` with one service, `portal`.
- `make compose-up` and `make compose-down`.
- A short "Docker" section in `app/README.md` (the one OPS-01 creates).

**Out of scope**

- The image itself: OPS-01.
- Supabase, Access and Anthropic variables. Each item that adds a variable
  (BE-26, BE-23, BE-03) adds it to the model and to `.env.example`, and
  Compose passes it through with no change here (section 3.3).
- A local Supabase container. The owner's decision is a *dev Supabase
  project*, never production.
- Reverse proxy, TLS and Cloudflare: OPS-04. Deploy: OPS-03.

## 3. Design

### 3.1 The service

`app/docker-compose.yml`:

```yaml
name: odiservices

services:
  portal:
    build:
      context: .
      dockerfile: Dockerfile
    image: odiservices-portal:local
    ports:
      - "127.0.0.1:${PORTAL_HOST_PORT:-8000}:8000"
    env_file:
      - path: .env
        required: false
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

- **Loopback only.** The port is published on `127.0.0.1`, so the portal is
  not reachable from the network while there is no auth (BE-23). The host
  port is `8000` unless `PORTAL_HOST_PORT` says otherwise.
- **Same image as the host.** The service builds from OPS-01's Dockerfile
  and adds nothing to it. No bind mount of the source, no `command`
  override. The healthcheck comes from the image.
- **Locked down.** A read-only root filesystem, no capabilities and
  `no-new-privileges`. The portal writes nothing to disk today. When BE-03
  needs a scratch directory for an upload, that item adds a named volume
  or a `tmpfs` entry, and its spec says so.
- **No volume for data.** Statements and extracted output never persist on
  this machine through Compose: no `input/`, no `outputs/` mount
  (`CLAUDE.md`, "Security and data").
- **Restart.** `"no"`: this file is for testing, so a crash must be visible.
  OPS-03 chooses the policy on the host.

### 3.2 Environment

- `PORTAL_ENV` is **not** set by the file, so the container runs as `prod`
  (BE-18's default). That is the point of the check: the packaged setup
  behaves like the host, including the BE-01 refusal to start without
  `web/dist`.
- Developers who want the dev behavior put `PORTAL_ENV=dev` in `app/.env`.
  Compose reads it through `env_file`. The dev bypass of BE-25 stays tied to
  that value.
- `app/.env` is optional (`required: false`). With none, the portal starts
  on defaults.
- `app/.env` is git-ignored and never enters the image: `.dockerignore`
  excludes it (OPS-01, 3.3), and Compose injects it at run time only.

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
| `make compose-up` with no `.env` | The image builds, and the command returns once the service is `healthy` |
| `docker compose ps` | One service, `portal`, `running (healthy)`, with the port `127.0.0.1:8000->8000/tcp` |
| `curl http://127.0.0.1:8000/healthz` | 200, `{"status":"ok"}` |
| `curl -i http://127.0.0.1:8000/categorizer/abc-123` | 200, `text/html` |
| The port is not on other interfaces: `lsof -nP -iTCP:8000 -sTCP:LISTEN` | Only `127.0.0.1`, never `*` or `0.0.0.0` |
| `docker compose exec portal id -u` | `10001` |
| `docker compose exec portal sh -c 'touch /app/x'` | Fails (read-only filesystem) |
| `PORTAL_HOST_PORT=8100 make compose-up` | The portal answers on `127.0.0.1:8100` |
| Optional `.env`: create `app/.env` with `PORTAL_LOG_LEVEL=DEBUG`, run `make compose-up` | The container's log level is `DEBUG` (the startup log line shows it). The script deletes the file afterwards |
| The image holds no `.env`: `docker compose exec portal sh -c 'find /app -name ".env*"'` while the file above exists on the host | Prints nothing |
| `docker compose logs portal` | JSON `request` events (BE-21), with no query string |
| `make compose-down` | The container and the network are gone. `docker compose ps` is empty |

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
| `test_has_one_portal_service` | `services` has only `portal`, built from `Dockerfile` with the context `.` |
| `test_port_is_loopback_only` | Every published port starts with `127.0.0.1:` |
| `test_env_file_is_optional` | `.env` is listed with `required: false` |
| `test_no_secret_or_data_in_file` | The file text has no `SUPABASE`, `KEY`, `SECRET` or `TOKEN`, and no volume or bind mount at all |
| `test_container_is_locked_down` | `read_only` is true, `cap_drop` has `ALL`, and `no-new-privileges:true` is set |

## 7. Open questions

1. **Guard against a production Supabase.** *Recommendation:* no code in
   this item. BE-26 decides how to tell the projects apart (for example a
   `PORTAL_SUPABASE_PROJECT` name that must match `PORTAL_ENV`).
2. **Default `PORTAL_ENV`.** Leaving it unset tests the packaged setup as
   production. *Recommendation:* keep that. Dev behavior is opt-in through
   `.env`.
3. **Dev profile with hot reload.** *Recommendation:* no. `make dev` already
   covers it, and a bind-mounted source would break the "same image as the
   host" rule.
4. **Read-only filesystem.** It may need a `tmpfs` entry once BE-03 handles
   uploads. *Recommendation:* keep it now, and let BE-03 add what it needs.
