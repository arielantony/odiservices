# Spec — OPS-01 Dockerfiles for the API and the web app

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-01 |
| **Depends on** | BE-33, BE-19, BE-20 |
| **Spec status** | In review. Rewritten 2026-10-30 after the owner asked for separate `api` and `web` images; replaces the single-image design |
| **Date** | 2026-10-30 |

## 1. Goal

Two container images, built and run separately:

- **`api`**: FastAPI (API only, BE-33).
- **`web`**: nginx serving the built React app and proxying `/api` and
  `/healthz` to the API.

The browser talks to `web` only, so it sees one origin: no CORS, and Cloudflare
Access (OPS-04) protects a single entry point. The same images run locally
(OPS-02) and on Lightsail (OPS-03). Neither holds a secret, a statement or test
code.

## 2. Scope

**In scope**

- `app/api/Dockerfile` and `app/api/.dockerignore` (context `app/api`).
- `app/web/Dockerfile`, `app/web/.dockerignore` and
  `app/web/nginx/default.conf.template` plus `app/web/nginx/headers.conf`
  (context `app/web`).
- `make docker-build` and `make check-image`.
- `app/scripts/check-image.sh`, the script that runs the checks in section 5.

**Out of scope**

- Running the images with Compose: OPS-02.
- Registry, deploy and the host: OPS-03. Cloudflare: OPS-04. Secrets on the
  host: OPS-05.
- A CSP header: BE-32 (it now goes in `headers.conf`).
- CI that builds the images: not in the backlog yet.

## 3. Design

### 3.1 The `api` image

Context `app/api`. Layout in the image: `/app/server/`.

- **Base:** `python:3.14-slim-bookworm`, pinned by tag and digest.
- **Install:** `pip install --no-cache-dir -r /tmp/requirements.txt`, then the
  file is deleted. Dev requirements are not installed. No uv in the image.
- **Non-root:** user `portal` (uid/gid 10001, no login shell, owns nothing
  writable). `USER portal` before `CMD`.
- **Environment:** `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`. The
  image sets no `PORTAL_*` value, so `PORTAL_ENV` defaults to `prod` (BE-18).
- **Port:** `EXPOSE 8000`.
- **Command:** `uvicorn server.main:create_app --factory --host 0.0.0.0
  --port 8000 --no-access-log`, working directory `/app`. `0.0.0.0` is the
  container's own network namespace; publishing is Compose's job (OPS-02).
  One uvicorn process.
- **Healthcheck:** `python -c` with `urllib.request` on
  `http://127.0.0.1:8000/healthz` (BE-20). No curl. Interval 30s, timeout 3s,
  start period 10s, 3 retries.

`app/api/.dockerignore` is an allow-list:

```
*
!requirements.txt
!server/
**/__pycache__/
**/*.pyc
**/*.pdf
**/.env
**/.env.*
```

### 3.2 The `web` image

Context `app/web`. Two stages.

| Stage | Base | Does |
|---|---|---|
| `build` | `node:24-bookworm-slim` | `corepack enable`, `yarn install --immutable`, `yarn build`. Copies `package.json`, `yarn.lock` and `.yarnrc.yml` first, so the install layer is cached until a dependency changes |
| `runtime` | `nginxinc/nginx-unprivileged` (a stable Debian tag, resolved at implementation) | Copies `dist` to `/usr/share/nginx/html` and the two nginx files |

Rules:

- **Pinned bases:** tag and digest on every `FROM`, resolved at
  implementation, changed only by a deliberate PR.
- **Non-root by the base:** `nginx-unprivileged` runs as uid 101 and listens
  on **8080**. `EXPOSE 8080`.
- **Upstream is a setting.** The config is a template
  (`/etc/nginx/templates/default.conf.template`, rendered with `envsubst` by
  the base image's entrypoint). `API_UPSTREAM` defaults to `api:8000`, the
  Compose service name and port.
- **Healthcheck:** a request to `http://127.0.0.1:8080/` with a tool already
  in the base image (chosen at implementation; nothing is installed). It does
  not depend on the API.

`app/web/.dockerignore`:

```
*
!package.json
!yarn.lock
!.yarnrc.yml
!.nvmrc
!index.html
!vite.config.ts
!tsconfig.json
!src/
!nginx/
**/*.pdf
**/.env
**/.env.*
```

This keeps `node_modules/`, `dist/`, `legacy/` and every `.env` out.

### 3.3 nginx behavior

It reproduces what BE-01 does today, so the browser sees the same responses:

| Request | Result |
|---|---|
| `/api/...` and `/healthz` | Proxied to `http://$API_UPSTREAM`. The API's own responses (JSON 404, headers) pass through |
| `/assets/...` | The file with `Cache-Control: public, max-age=31536000, immutable`, or 404 |
| A path whose last segment has a file extension and matches no file (`/.env`, `/missing.js`) | 404, never `index.html` |
| A file in `dist` (`/favicon.ico`) | That file |
| Any other path (`/`, `/categorizer`, `/categorizer/abc-123`) | `index.html` with `Cache-Control: no-cache` |
| Every response nginx generates | `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` |

Implementation rules:

- The three headers live in `nginx/headers.conf`, included in every
  `location` with `always`. `add_header` in a `location` discards the ones
  from `server`, so a single `server`-level line would silently drop them.
- `server_tokens off`. The proxy forwards `Host` only. It
  never logs query strings: `access_log off`, and the API's request log
  (BE-21) is the record.
- Proxy headers: no `X-Forwarded-For` is added or logged (no IPs in logs).
  Cloudflare headers are OPS-04's decision.
- Hidden files are never served, even if one lands in `dist`.

### 3.4 Make targets

`app/Makefile`:

| Target | Runs |
|---|---|
| `docker-build` | `docker build -t odiservices-api:local api` and `docker build -t odiservices-web:local web` |
| `check-image` | `scripts/check-image.sh` |

`help` lists both. Tags for a registry are OPS-03's decision.

## 4. Files

| File (in `app/`) | Change |
|---|---|
| `api/Dockerfile`, `api/.dockerignore` | New. 3.1 |
| `web/Dockerfile`, `web/.dockerignore` | New. 3.2 |
| `web/nginx/default.conf.template`, `web/nginx/headers.conf` | New. 3.3 |
| `scripts/check-image.sh` | New. Builds both images and runs section 5 on a throwaway network, then removes everything it created. Exits non-zero on the first failed check |
| `Makefile` | `docker-build` and `check-image` |
| `api/tests/test_dockerignore.py` | New. Section 6 |
| `README.md` | A "Docker" section |

## 5. Verification

Docker must be running. Each check runs in `scripts/check-image.sh`; `make
check-image` runs them all on a throwaway network, container names and a free
port. Nothing reaches the network beyond pulling base images and the Yarn and
pip packages.

**Both images**

| Check | Expected |
|---|---|
| `make docker-build` | Both images build from a clean checkout. After a change only in `web/src/`, the second build shows `CACHED` for the `yarn install` step. After a change only in `api/server/`, the `pip install` step is `CACHED` |
| Planted files: create `app/api/.env`, `app/web/.env`, `app/api/input/x.pdf` and `app/web/outputs/x.json`, then build | None is in either image (`find` for `.env*`, `*.pdf`, `input`, `outputs` finds nothing). The script deletes them, and refuses to run if any already exists |

**`api` image**

| Check | Expected |
|---|---|
| `id -u` | `10001` |
| Content of `/app` | Only `server`. No `tests`, `fixtures`, `web`, `node_modules` or `.venv` |
| Start with no configuration (prod, no `dist` anywhere) | `running`; the log shows BE-21 `request` events as JSON, with no query string |
| `GET /healthz` on its own network | 200, `{"status":"ok"}` |
| `GET /api/nope` | 404, the JSON `not_found` body |
| `docker inspect` health | `healthy` within 60 seconds |
| `import server.main` with no `PORTAL_*` set | Succeeds |

**`web` image** (started with `API_UPSTREAM` pointing at the check's `api`
container)

| Check | Expected |
|---|---|
| `id -u` | `101` |
| `nginx -t` inside the container | Passes |
| Content of `/usr/share/nginx/html` | `index.html` and `assets/` only. No source, `.env` or `node_modules` |
| `GET /` and `GET /categorizer/abc-123` | 200, `text/html`, `<div id="root">`, `Cache-Control: no-cache` |
| `GET /assets/<hashed js>` | 200, `Cache-Control: public, max-age=31536000, immutable` |
| `GET /.env`, `GET /ask_pdf.py`, `GET /assets/missing.js` | 404 |
| The three security headers | Present on `/`, on an asset, on a 404 and on a proxied `/healthz` |
| `GET /healthz` and `GET /api/nope` through the web port | 200 `{"status":"ok"}`, and the JSON 404 from the API |
| Query strings: `GET /healthz?token=abc123`, then both containers' logs | `abc123` appears in neither |
| `docker inspect` health | `healthy` within 60 seconds, also with the `api` container stopped |

Also required for **Done**: `make test-api` still passes (it includes the
`.dockerignore` test).

The images are never run with a real `.env`, and no statement is ever put in a
build context or a container.

## 6. Tests

`app/api/tests/test_dockerignore.py` (pure Python, no Docker, no network). It
reads `api/.dockerignore` and `web/.dockerignore` as text, for each file:

| Test | Asserts |
|---|---|
| `test_ignores_everything_by_default` | The first rule is `*` |
| `test_never_allows_sensitive_paths` | No `!` rule re-allows `.env`, `input`, `outputs`, `fixtures`, `legacy`, `tests` or a `.pdf` |
| `test_blocks_env_and_pdf_anywhere` | `**/.env`, `**/.env.*` and `**/*.pdf` are listed |
| `test_allows_what_the_build_needs` | The API file allows `requirements.txt` and `server/`. The web file allows `package.json`, `yarn.lock`, `src/` and `nginx/` |

The image checks in section 5 are the integration tests. They need Docker, so
they run through `make check-image` and not in `make test`.

## 7. Open questions

1. **Digest pinning.** *Recommendation:* pin tag and digest on all three bases.
2. **`pip` or `uv` in the api image.** *Recommendation:* `pip`; the install
   runs only when `requirements.txt` changes.
3. **Base images.** `slim-bookworm` for Python; `nginx-unprivileged` for web.
   *Recommendation:* these. Alpine breaks `uvloop` and `httptools` wheels.
4. **Tags and registry.** *Recommendation:* `odiservices-api:local` and
   `odiservices-web:local` here; OPS-03 chooses the scheme.
5. **Workers.** *Recommendation:* one uvicorn process; revisit in OPS-03.
6. **nginx request log.** Off here, because a query string must never be
   logged. *Recommendation:* keep it off; BE-21's log is the record.
