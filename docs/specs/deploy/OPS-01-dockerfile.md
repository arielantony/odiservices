# Spec — OPS-01 Dockerfile for the portal

| | |
|---|---|
| **Backlog** | Packaging and deployment › Infrastructure › OPS-01 |
| **Depends on** | BE-01, BE-19, BE-20 |
| **Spec status** | In review |
| **Date** | 2026-10-30 |

## 1. Goal

One container image that runs the whole portal: FastAPI serving the built
React app (BE-01). The same image runs locally (OPS-02) and on Lightsail
(OPS-03). It holds no secret, no statement and no test code.

## 2. Scope

**In scope**

- `app/Dockerfile`, a two-stage build (`docs/proposals/monorepo-and-react.md`).
- `app/.dockerignore`.
- `make docker-build`.
- `app/scripts/check-image.sh`, the script that runs the checks in section 5.

**Out of scope**

- Running the image with Compose: OPS-02.
- Registry, deploy and the host: OPS-03. Cloudflare: OPS-04. Secrets on the
  host: OPS-05.
- A CSP header: BE-32.
- CI that builds the image: not in the backlog yet.

## 3. Design

### 3.1 Build context and layout

The build context is `app/`. `docker build -f Dockerfile .` runs from there.
The image has this layout, so `DEFAULT_FRONTEND_DIR` in
`server/frontend.py` (`<root>/web/dist`) resolves with no setting:

```
/app/api/server/        the FastAPI package
/app/web/dist/          the built React app
```

### 3.2 Stages

| Stage | Base | Does |
|---|---|---|
| `web` | `node:24-bookworm-slim` | `corepack enable`, `yarn install --immutable`, `yarn build` in `/build/web`. Copies `package.json`, `yarn.lock` and `.yarnrc.yml` first, so the install layer is cached until a dependency changes |
| `runtime` | `python:3.14-slim-bookworm` | `pip install --no-cache-dir -r /tmp/requirements.txt`, deletes it, then copies `api/server/` and `web/dist/` from the `web` stage. Dev requirements are not installed |

Rules:

- **Pinned bases.** Each `FROM` names the tag and its digest
  (`image:tag@sha256:…`). The implementation resolves the digests and
  records them in the Dockerfile. A digest changes only by a deliberate PR.
- **Same versions as local.** Node 24 (`app/web/.nvmrc`), Python 3.14
  (`make setup-api`), and the exact pins of `requirements.txt` (BE-19).
- **No uv in the image.** `pip` installs the pinned `requirements.txt`, which
  is already compiled. It needs no extra package.
- **Non-root.** A fixed user `portal` (uid/gid 10001) with no login shell
  owns nothing writable. `USER portal` before `CMD`.
- **No bytecode, no buffering.** `PYTHONDONTWRITEBYTECODE=1`,
  `PYTHONUNBUFFERED=1`, so logs reach `docker logs` at once (BE-21 logs to
  stdout).
- **Port.** `EXPOSE 8000`.
- **Command.** `uvicorn server.main:create_app --factory --host 0.0.0.0
  --port 8000 --no-access-log`, with the working directory `/app/api`. The
  host is `0.0.0.0` because the container's own network namespace is the
  boundary. Publishing the port to the outside is the job of Compose
  (OPS-02) and of OPS-04.
- **Environment.** The image sets no `PORTAL_*` value. `PORTAL_ENV` defaults
  to `prod` (BE-18), so a container started with no configuration behaves
  like production: it refuses to start without `web/dist` (BE-01).
- **Healthcheck.** `HEALTHCHECK` runs `python -c` with `urllib.request` on
  `http://127.0.0.1:8000/healthz` (BE-20). The slim image has no curl, and
  none is installed. Interval 30s, timeout 3s, start period 10s, 3 retries.

### 3.3 `.dockerignore`

`app/.dockerignore` starts from "ignore everything" and allows only what the
build needs:

```
*
!api/requirements.txt
!api/server/
!web/package.json
!web/yarn.lock
!web/.yarnrc.yml
!web/.nvmrc
!web/index.html
!web/vite.config.ts
!web/tsconfig.json
!web/src/
**/__pycache__/
**/*.pyc
**/*.pdf
**/.env
**/.env.*
```

Consequences, each intended:

- `.env`, `.env.*`, `input/`, `outputs/` and every `*.pdf` never reach the
  build, even if one is dropped into `app/` by mistake
  (`CLAUDE.md`, "Security and data").
- `api/tests/`, `api/.venv/`, `web/node_modules/`, `web/legacy/`,
  `web/dist/` and `fixtures/` are excluded, so the image holds no test
  fixture and no vanilla portal. The build creates `dist` itself.
- Adding a file the build needs means adding an explicit `!` line.

### 3.4 Make target

`app/Makefile` gets `docker-build`: `docker build -t odiservices-portal:local .`
(`help` lists it). The image tag for a registry is OPS-03's decision.

## 4. Files

| File (in `app/`) | Change |
|---|---|
| `Dockerfile` | New. Section 3.2 |
| `.dockerignore` | New. Section 3.3 |
| `scripts/check-image.sh` | New. Builds the image and runs the section 5 checks, then removes its container. Exits non-zero on the first failed check |
| `Makefile` | `docker-build` and `check-image` targets |
| `api/tests/test_dockerignore.py` | New. Section 6 |
| `README.md` | A "Docker" section with the two targets |

## 5. Verification

Docker must be running. Each check runs in `scripts/check-image.sh`, and
`make check-image` runs them all. The script uses a throwaway container name
and a free port, and never touches the network beyond pulling the base images.

| Check | Expected |
|---|---|
| `make docker-build` | The image builds from a clean checkout. A second build, after touching only a file in `web/src/`, reuses the dependency layers (the log shows `CACHED` for both installs) |
| `docker run --rm odiservices-portal:local id -u` | `10001`, not `0` |
| Planted secrets: create `app/.env` with the line `PORTAL_ENV=dev`, an empty `app/input/x.pdf` and `app/outputs/x.json`, then build | None of the three is in the image (`find / -name .env -o -name '*.pdf' -o -path '*/input/*' -o -path '*/outputs/*'` under `/app` finds nothing). The script deletes the planted files afterwards |
| Content of `/app` | Only `api/server` and `web/dist` (the requirements file is copied in an earlier layer, outside `/app`). No `tests`, `fixtures`, `legacy`, `node_modules` or `.venv` |
| Start with no configuration | The container is `running`, and the log shows the BE-21 `request` events as JSON lines, with no query string |
| `GET /healthz` on the published port | 200, `{"status":"ok"}` |
| `GET /` and `GET /categorizer/abc-123` | 200, `text/html`, and the page contains `<div id="root">` |
| `GET /assets/<hashed js>` | 200, `Cache-Control: public, max-age=31536000, immutable` |
| `GET /.env` and `GET /ask_pdf.py` | 404 |
| `docker inspect` health status | `healthy` within 60 seconds |
| Break the image: run with `-v $(mktemp -d):/app/web/dist` (an empty `dist`) | The container exits at startup with the BE-01 message "Frontend build not found", and exit code 1 |
| Production values: `docker run --rm odiservices-portal:local python -c "import server.main"` | Succeeds, with no `PORTAL_*` variable set |

Also required for **Done**: `make test-api` still passes (the new
`.dockerignore` test is part of it).

The image is never run with a real `.env`, and no statement is ever put in
the build context or in a container.

## 6. Tests

`app/api/tests/test_dockerignore.py` (pure Python, no Docker, no network).
It reads `app/.dockerignore` as text:

| Test | Asserts |
|---|---|
| `test_ignores_everything_by_default` | The first rule is `*` |
| `test_never_allows_sensitive_paths` | No `!` rule re-allows `.env`, `input`, `outputs`, `fixtures`, `legacy`, `tests` or a `.pdf` |
| `test_blocks_env_and_pdf_anywhere` | `**/.env`, `**/.env.*` and `**/*.pdf` are listed |
| `test_allows_what_the_build_needs` | `api/requirements.txt`, `api/server/`, `web/package.json`, `web/yarn.lock` and `web/src/` are allowed |

The image checks in section 5 are the integration tests. They need Docker, so
they run through `make check-image` and not in `make test`.

## 7. Open questions

1. **Digest pinning.** A digest makes the build reproducible but needs a PR
   to take a base-image security patch. *Recommendation:* pin tag and digest
   now, as BE-19 did for packages, and revisit when CI exists.
2. **`pip` or `uv` in the image.** `uv` installs faster, but adds a binary and
   a base image to pin. *Recommendation:* `pip`. The install runs only when
   `requirements.txt` changes.
3. **Base image.** `slim-bookworm` or Alpine. *Recommendation:* slim. Alpine
   uses musl, and some wheels (`uvloop`, `httptools`, from
   `uvicorn[standard]`) are not published for it, which means compiling.
4. **Image tag and registry.** *Recommendation:* `odiservices-portal:local`
   here, and OPS-03 chooses the registry and the tag scheme.
5. **Multiple workers.** *Recommendation:* one uvicorn process. The portal is
   internal, and the load doesn't justify a process manager. Revisit in OPS-03
   if the host needs it.
