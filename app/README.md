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
