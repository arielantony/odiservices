# Spec — BE-17 Create the FastAPI project

| | |
|---|---|
| **Backlog** | Platform › Project foundation › BE-17 |
| **Needed by** | BE-01, and every later backend item |
| **Depends on** | — |
| **Spec status** | Approved, 2026-10-30. Sections 3.1 to 3.4 were updated the same day for the approved monorepo/React proposal |
| **Date** | 2026-10-30 |

## 1. Goal

A FastAPI application that runs locally with one command, serves the portal
(BE-01), and is the home of every later endpoint. It replaces `kanban/serve.py`.

## 2. Scope

**In scope:** the project layout, the application factory, the run command and
the removal of `kanban/`.

**Out of scope:**

| Excluded | Covered by |
|---|---|
| Settings | BE-18 |
| Dependency pins | BE-19 |
| `/healthz` | BE-20 |
| Request logging | BE-21 |
| Serving the pages | BE-01 |
| OpenAPI | BE-22 |
| Auth | BE-23 to BE-25 |
| Database | BE-26 and later |
| Docker | OPS-01 |

## 3. Design

### 3.1 Layout

`app/` is a monorepo (`docs/proposals/monorepo-and-react.md`, approved). This
item creates the root files and `api/`. FE-23 creates `web/`.

```
app/
├── Makefile              # root entry point: dev, serve, test, test-api (web targets added by FE-23)
├── README.md             # how to run everything
├── .env.example          # BE-18
├── fixtures/             # fictitious shared test data (QA-01)
└── api/
    ├── requirements.in / requirements.txt            # BE-19
    ├── requirements-dev.in / requirements-dev.txt    # BE-19, test harness
    ├── server/           # Python package
    │   ├── __init__.py
    │   ├── main.py       # create_app() and the module-level `app`
    │   ├── settings.py   # BE-18
    │   ├── request_log.py  # BE-21
    │   └── routes/
    │       ├── __init__.py
    │       └── health.py   # BE-20
    └── tests/
        └── conftest.py
```

Commands run from `app/` through the Makefile. Python commands run with
`api/` as the working directory. The Docker build context (OPS-01) is `app/`.

### 3.2 Application factory

`server/main.py` exposes `create_app(settings: Settings | None = None) ->
FastAPI` and a module-level `app = create_app()`. Tests build their own app
with explicit settings. The factory registers, in this order:

1. middleware (request log, security headers);
2. API routers (`/healthz`, then `/api/...` as items land);
3. the frontend mount and the SPA fallback (BE-01). They come last, so they
   never shadow a route.

### 3.3 Python and tooling

- **Python 3.14.** The same version is used for the OPS-01 base image.
- **Virtual environment:** created with `uv` at `app/api/.venv/`, which is
  added to `app/.gitignore`. The owner authorized creating it and installing
  the pinned requirements when implementation starts (2026-10-30).

### 3.4 Run commands

| Command (in `app/`) | Runs |
|---|---|
| `make dev` | `uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log`, in `api/`. FE-23 adds Vite on port 5173, which proxies `/api` and `/healthz` to it |
| `make serve` | uvicorn without `--reload`, serving the built frontend (`web/dist/`, BE-01), so the setup is close to production |
| `make test-api` | pytest in `api/` |

The server binds to localhost only. The access log is off because BE-21
replaces it.

### 3.5 Removing `kanban/`

The board already lives in `app/portal/categorizer/` (and moves to
`app/web/legacy/` with FE-23). `kanban/` is untracked by
git, so removing it cannot be undone from the repo. Before deleting it, add it
to a tarball in `~/odiservices-backups/` (the same place as the bootstrap
backup), then delete it, and record both steps in the backlog.

## 4. Verification

| Check | Expected |
|---|---|
| `make dev`, then `curl -i http://127.0.0.1:8000/healthz` | 200 |
| Server bind address | `127.0.0.1` only |
| `create_app()` called twice in one process | Two independent apps, no shared global state |
| `kanban/` | Gone, and the backup tarball lists its files |

## 5. Tests

`app/api/tests/test_app.py`, with no fixture data:

| Test | Asserts |
|---|---|
| `test_create_app_returns_independent_instances` | Two `create_app()` calls return different apps, and a route added to one is absent from the other |
| `test_create_app_accepts_explicit_settings` | The app uses the `Settings` passed in, not the environment |
| `test_routes_registered_before_static_mount` | The static mount is the last route, so `/healthz` and `/api` are never shadowed |

This item also creates the backend test harness: `requirements-dev.in`
(pytest, httpx), `tests/conftest.py` with a `client` fixture built from
`create_app(test_settings)`, and `make test-api`. It replaces the setup part
of QA-01.

## 6. Open questions

Answers (2026-10-30):

- **Q1:** `app/` is a monorepo for the backend and the frontend, with the
  layout in `docs/proposals/monorepo-and-react.md` (approved). Section 3.1
  reflects it.
- **Q2:** Python 3.14.
- **Q3:** remove `kanban/`, with the backup step in 3.5.

1. **Project location:** BE-17 and OPS-01 say `portal/` at the repo root, but
   the bootstrap created `app/portal/` for the static site.
   *Recommendation:* `app/` is the project and `app/server/` is the Python
   package, as in 3.1. It keeps the server next to the files it serves, and
   `app/.gitignore` already ignores `.env`. OPS-01's build context becomes
   `app/`.
2. **Python version:** 3.15 is installed locally and FastAPI's dependencies
   already ship wheels for it, but 3.15 has only just come out.
   *Recommendation:* 3.14, which is mature and has a slim Docker base. Revisit
   3.15 later.
3. **Removing `kanban/`:** *Recommendation:* back it up as in 3.5, then
   delete it.
