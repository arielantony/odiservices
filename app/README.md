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
| `make serve` | API only, serving `web/dist/` once BE-01 lands |
| `make test` | API and web tests |
| `make test-api` | pytest in `api/` |

## Docker

| Command | Runs |
|---|---|
| `make docker-build` | Builds the portal image, `odiservices-portal:local` (needs Docker) |
| `make check-image` | Builds it and runs the OPS-01 checks: user, contents, health, routes |

The image holds only `api/server` and `web/dist`. `.dockerignore` lists what
the build may read, so `.env`, PDFs, `input/` and `outputs/` never enter it.

