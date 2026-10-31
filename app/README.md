# OdiServices Portal app

Monorepo: `api/` (FastAPI, Python 3.14) and `web/` (React, Vite). Run every
command from `app/`.

## Setup

```bash
cd api
uv venv --python 3.14 .venv
uv pip sync requirements-dev.txt --python .venv/bin/python
uv pip install -r requirements.txt --python .venv/bin/python
cd .. && make setup-web
```

## Commands

| Command | Runs |
|---|---|
| `make dev` | API on 127.0.0.1:8000 (reload) and Vite on 127.0.0.1:5173 |
| `make serve` | API only, no pages (use `make dev` for the app) |
| `make test` | API and web tests |
| `make test-api` | pytest in `api/` |

## Docker

| Command | Runs |
|---|---|
| `make docker-build` | Builds `odiservices-api:local` and `odiservices-web:local` (needs Docker) |
| `make check-image` | Builds both and runs the OPS-01 checks: users, contents, routes, health, headers, logs |

`api` is FastAPI only. `web` is nginx: it serves the built app and proxies
`/api` and `/healthz` to `api:8000` (`API_UPSTREAM` changes the target), so the
browser sees one origin. Each image's `.dockerignore` lists what its build may
read, so `.env`, PDFs, `input/` and `outputs/` never enter either image.
