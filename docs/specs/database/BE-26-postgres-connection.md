# Spec — BE-26 Use Supabase as the backend database

| | |
|---|---|
| **Backlog** | Platform › Database › BE-26 |
| **Depends on** | BE-17, BE-18 |
| **Spec status** | In review |
| **Date** | 2026-11-02 |

## 1. Goal

The API can open a connection to its database, with the same code in
development and in production. Production is the owner's one Supabase
project. Development is a local Postgres in Docker, the closest thing to it
(owner decision, 2026-11-02: one production database, no separate dev
project). The credential stays on the server. This item ships the
connection and nothing that uses it: no table, no migration, no route. The
tables are BE-27 to BE-30, the migrations and the roles are BE-31, and the
first code that reads or writes is BE-24.

## 2. Scope

**In scope**

- The setting `PORTAL_DATABASE_URL` and its validation.
- The package `server/db/`: `build_engine` (a SQLAlchemy engine for Postgres
  through psycopg 3) and `check_database` in `engine.py`, plus `python -m
  server.db`, a command that proves a connection works. It is a package so
  the ORM models of BE-27 onwards have a place to live.
- A local Postgres in Docker, in its own Compose file that production never
  reads.
- `make db-up`, `db-down`, `db-check` and `test-db`.
- The guard rails of section 3.2: a remote host needs TLS, and `PORTAL_ENV=dev`
  refuses a remote host.
- Pinning the runtime packages.

**Out of scope**

- Migrations, the schema, the `app_backend` role, RLS, Alembic and the
  runbook for the host: BE-31.
- The `users`, `statements` and `transactions` tables and the categories:
  BE-27 to BE-30.
- Wiring the engine into `create_app()` and a per-request ORM session
  dependency: BE-24, the first code that needs them. Adding them now would be
  code nothing calls.
- The ORM base class (`DeclarativeBase`, the naming convention) and the test
  that keeps the models and the migrations in step: BE-31, because Alembic's
  `env.py` needs the metadata. The models themselves arrive with each table,
  from BE-27.
- A readiness route that checks the database. `/healthz` stays independent of
  it, so the deploy checks keep passing (OPS-03).
- Backups and point-in-time recovery of the Supabase project: depends on the
  plan and is the owner's to decide.

## 3. Design

### 3.1 Direct Postgres, not the Supabase HTTP API

FastAPI talks to Postgres with a driver. It does not use `supabase-py` and
the project's REST API. Reasons (confirmed by the owner, 2026-11-02): the same
code runs against a local Postgres, and an import (BE-05) writes a statement
and its transactions in one transaction.

The data layer is **SQLAlchemy 2.0 with the ORM**, in the typed style
(`Mapped[...]`), and a synchronous `Session`. The owner chose it on
2026-11-02 for the long run: the portal will host many services, and the
first consumer (BE-24) sets the pattern that every later one follows. The
models arrive with each table (BE-27 to BE-30). The migrations stay
hand-written SQL (BE-31), because they carry what the models cannot: the
schema, the roles, RLS and its policies. `text()` stays available for the
cases where plain SQL is clearer.

Consequence: the secret is a database connection string, not the
service-role key. The rule in `CLAUDE.md` and `docs/BACKEND_GUIDELINES.md` is
reworded to say so, in the implementation PR (section 3.6). The principle is
unchanged: the credential stays on the server and never reaches the browser,
a response, a log or the repository.

### 3.2 The setting

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `PORTAL_DATABASE_URL` | secret string | unset | `postgresql+psycopg://<user>[:<password>]@<host>[:<port>]/<database>[?sslmode=...]` |

Held as `SecretStr` (BE-18 pattern), so it is never printed.

- **Format.** The scheme must be `postgresql+psycopg`, and a host and a
  database name are required. Anything else fails at startup. The error
  names `PORTAL_DATABASE_URL` and never prints the value.
- **TLS.** A host that is not loopback (`127.0.0.1`, `::1`, `localhost`) must
  carry `sslmode=require`, `verify-ca` or `verify-full`. Without it startup
  fails. A forgotten parameter would send the password in clear text.
- **`PORTAL_ENV=dev` refuses a remote host.** Development uses the local
  Postgres only. With one production database, a leftover variable in a
  shell must not make a local run write to it. `make dev` sets
  `PORTAL_ENV=dev` unless it is already set.
- **Unset.** The server starts, as it does today. Nothing reads the database
  yet, and `/healthz` stays up.

### 3.3 The engine (`server/db/engine.py`)

```python
def build_engine(url: SecretStr) -> Engine
def check_database(engine: Engine) -> DatabaseInfo   # role, server major version
```

| Option | Value | Why |
|---|---|---|
| `pool_size` / `max_overflow` | 3 / 2 | The host is small and runs one worker |
| `pool_pre_ping` | `True` | A pooler closes idle connections |
| `pool_recycle` | 300 s | Same |
| `connect_args["prepare_threshold"]` | `None` | No server-side prepared statements, which a transaction-mode pooler breaks |
| `connect_args["connect_timeout"]` | 5 s | A down database must not hang a request |
| `connect_args["application_name"]` | `odiservices-api` | Visible in `pg_stat_activity` |
| `echo` | `False`, always | SQL text and parameters can hold transaction data (BE-21) |

`check_database` runs `select current_user, current_setting('server_version_num')`
and returns the role and the major version.

`python -m server.db` loads the settings, calls `check_database` and prints
one line:

- success: `database ok (role=<role>, postgres=<major>)`, exit 0;
- failure: `database unavailable: <exception class name>`, exit 1. It prints
  the class only, never the message, because a driver message can contain the
  host and the user. With no `PORTAL_DATABASE_URL` it prints
  `database not configured`, exit 1.

The role name is not a secret, and it is what shows later (BE-31) that the
server connects as `app_backend` and not as the owner.

### 3.4 The local Postgres

`app/docker-compose.db.yml`, a separate file with its own project name
(`odiservices-dev-db`):

- image `postgres:${PORTAL_DB_PG_MAJOR:-17}`;
- published on `127.0.0.1:55432` only;
- user and database `odiservices`, `POSTGRES_HOST_AUTH_METHOD=trust`. The
  port is loopback-only, so there is no password to keep, and the dev URL
  holds no secret;
- a named volume, so data survives `make db-down`, and a `pg_isready`
  health check.

It is a separate file on purpose. `deploy.sh` runs `docker compose -f
docker-compose.yml -f docker-compose.prod.yml`, so a service added to either
of those would start on the Lightsail host. A test and a verification check
keep it that way (section 4, checks 7).

| Target (in `app/`) | Does |
|---|---|
| `make db-up` | Starts the local Postgres and waits until it is healthy |
| `make db-down` | Stops it, keeping the data (`make db-down V=1` also removes the volume) |
| `make db-check` | `python -m server.db` against `$PORTAL_DATABASE_URL`, which defaults to `postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices` |
| `make test-db` | `db-up`, then the tests marked `db`. `make test-api` never runs them |

`PORTAL_DB_PG_MAJOR` stays at 17 until the owner confirms the major version
of the Supabase project (section 7). A local version that differs from
production is the one fidelity gap, and it is recorded, not hidden.

### 3.5 Tests that need Postgres

Tests marked `db` need the local Postgres and run only through
`make test-db`. `pytest.ini` gets `addopts = -m "not db"`, so `make test-api`
needs no Docker and calls no database. No test reaches Supabase.

### 3.6 Files

| File | Change |
|---|---|
| `app/api/server/db/__init__.py`, `engine.py`, `__main__.py` | New package: `build_engine`, `check_database`, `DatabaseInfo` and the `python -m server.db` entry |
| `app/api/server/settings.py` | The field and the three rules of 3.2 |
| `app/api/requirements.in`, `requirements.txt` | Add `sqlalchemy`, `psycopg[binary]`, compiled with `uv pip compile` |
| `app/api/pytest.ini` | `addopts = -m "not db"` and the `db` marker |
| `app/docker-compose.db.yml` | New: the local Postgres |
| `app/docker-compose.yml` | The header comment says "dev Supabase project"; reword it (there is none) |
| `app/Makefile` | The four targets, `PORTAL_ENV` default in `dev`, `help` lines |
| `app/.env.example` | The name `PORTAL_DATABASE_URL`, with a comment |
| `CLAUDE.md` | The security rule: the database credentials (connection strings and passwords) stay on the server |
| `docs/BACKEND_GUIDELINES.md` | Data section: direct Postgres, the two environments, the guard rails |
| `docs/BACKLOG.md` | BE-26 status and PR links; BE-25 note: local development uses the local Postgres only |

About 320 changed lines with the tests, one pull request.

## 4. Verification

Every check runs when the item merges. *Owner* checks need the owner's
Supabase project. Check 9 is blocked until the owner confirms the project's
details (section 7), and the item is not Done without it.

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make db-up && make db-check` | `database ok (role=odiservices, postgres=17)` |
| 3 | `make test-db` | The `db` tests pass |
| 4 | `PORTAL_DATABASE_URL='postgresql+psycopg://u:SENHA-FICTICIA@db.example.com/x' make serve` | Startup fails, the message names `PORTAL_DATABASE_URL` (TLS rule) and the output does not contain `SENHA-FICTICIA` |
| 5 | `PORTAL_ENV=dev PORTAL_DATABASE_URL='postgresql+psycopg://u@db.example.com/x?sslmode=require' make serve` | Startup fails, the message names `PORTAL_DATABASE_URL` (remote host in dev) |
| 6 | `make serve` with no `PORTAL_DATABASE_URL`, then `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz` | The server starts and the second command prints `200` |
| 7 | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --no-env-resolution --services` | `api` and `web` only, no `db` |
| 8 | `make docker-build`, then `docker run --rm --entrypoint python odiservices-api:local -c 'import psycopg, sqlalchemy; print("ok")'` | `ok` (the pinned wheels install in the read-only image) |
| 9 | *Owner:* with the owner's connection string in `~/.config/odiservices/supabase.env` (section 7): `set -a; . ~/.config/odiservices/supabase.env; set +a; PORTAL_DATABASE_URL="$PORTAL_MIGRATION_DATABASE_URL" make db-check` | `database ok (role=postgres, postgres=<major>)`: the engine settings work against the real service from the owner's machine |
| 10 | `git grep -nE 'postgres(ql)?(\+psycopg)?://[^ ]*:[^ @]+@' -- . ':!app/api/tests' ':!docs/specs'` | No match: no connection string with a password in the repository |

## 5. Tests

`app/api/tests/`. No test connects to Supabase, and `make test-api` needs no
Docker. Hosts and passwords are obviously fictitious (`db.example.com`,
`SENHA-FICTICIA`).

`test_settings.py` (additions)

| Test | Asserts |
|---|---|
| `test_database_url_optional` | Not set: `Settings()` builds and the field is `None` |
| `test_database_url_scheme` | `postgresql://…`, `mysql://…` and `x` fail, naming `PORTAL_DATABASE_URL` |
| `test_database_url_needs_host_and_name` | A URL with no host or no database name fails |
| `test_remote_host_needs_tls` | A remote host without `sslmode`, or with `sslmode=disable` or `prefer`, fails. `require`, `verify-ca` and `verify-full` pass |
| `test_loopback_host_needs_no_tls` | `127.0.0.1`, `::1` and `localhost` pass without `sslmode` |
| `test_dev_refuses_remote_host` | `PORTAL_ENV=dev` with a remote host fails. With a loopback host it passes. `prod` accepts a remote host |
| `test_database_url_never_printed` | None of the errors above, and `repr(Settings(...))`, contain the password |

`test_db.py`

| Test | Asserts |
|---|---|
| `test_engine_options` | Pool size and overflow, `pool_pre_ping`, `echo` off, `prepare_threshold` `None`, the connect timeout and the application name. The engine is lazy, so nothing connects |
| `test_engine_url_is_psycopg` | `build_engine` uses the `postgresql+psycopg` driver |
| `test_check_database_returns_role_and_major` | With a fake engine: the role and the major version come back |
| `test_cli_success_line` | `python -m server.db` with a fake engine prints `database ok (role=…, postgres=…)`, exit 0 |
| `test_cli_failure_prints_class_only` | The fake raises an error whose message holds a host and a user: the output has the class name and neither |
| `test_cli_not_configured` | No setting: `database not configured`, exit 1 |

`test_deploy_files.py` (addition)

| Test | Asserts |
|---|---|
| `test_prod_compose_has_no_database_service` | Neither `docker-compose.yml` nor `docker-compose.prod.yml` defines a `db` service, and `deploy.sh` does not name `docker-compose.db.yml` |

`test_db_live.py`, marked `db`, runs only in `make test-db`

| Test | Asserts |
|---|---|
| `test_local_postgres_answers` | `check_database` against the local Postgres returns the role `odiservices` |
| `test_prepared_statements_off` | The connection reports no server-side prepared statements after repeated identical queries |

## 6. Open questions

| # | Question | Recommended |
|---|---|---|
| 1 | Is there an ORM? | **Decided by the owner, 2026-11-02: yes, SQLAlchemy 2.0 with the ORM.** The portal will host many services, and the pattern is set by the first consumer. The risk is that models and migrations drift apart, so BE-31 adds a test that fails when they do. The migrations stay hand-written, because autogenerate does not understand RLS, policies or roles |
| 2 | TLS to Supabase: `require` or `verify-full`? | **`require` now.** The traffic is encrypted. `verify-full` also needs the project's CA certificate shipped to the host, which is more to maintain. Revisit with OPS-05 |
| 3 | Local Postgres version | **17** until the owner confirms the Supabase version, then the same major |
| 4 | Wire the engine into `create_app()` here? | **No.** BE-24 is the first caller |

A question with no answer becomes an assumption with the recommended option.

## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| Docker is running | Agent | `docker info --format '{{.ServerVersion}}'` | A version number |
| The Postgres image pulls | Agent | `docker pull -q postgres:17` | An image id (`sha256:…`) |
| Port 55432 is free | Agent | `lsof -nP -iTCP:55432 -sTCP:LISTEN \| wc -l` | `0` |
| The packages resolve for Python 3.14 | Agent | `printf 'sqlalchemy\npsycopg[binary]\n' > "$SCRATCH/in.txt" && uv pip compile --python-version 3.14 "$SCRATCH/in.txt"` | `sqlalchemy`, `psycopg`, `psycopg-binary` (run 2026-11-02: 2.1.6, 3.3.6 and 3.3.6, plus `typing-extensions`, already pinned) |
| **Supabase project details: region, Postgres major version, plan** | **Owner** | Read in the Supabase dashboard (Project Settings) and tell the agent | **Pending: the owner is confirming (2026-11-02).** The owner agreed to write and approve this spec without it. Needed for check 9, for `PORTAL_DB_PG_MAJOR` and for BE-31 |
| The connection string in a private file | Owner | `stat -f '%Lp' ~/.config/odiservices/supabase.env` | `600`. The file holds `PORTAL_MIGRATION_DATABASE_URL`, the owner role over the **session pooler**, with `sslmode=require`. The agent never reads it |
| The string works | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; psql "${PORTAL_MIGRATION_DATABASE_URL/+psycopg/}" -Atc 'select current_user'` | `postgres` |

**Packages this item installs** (and only these), all pinned by
`uv pip compile` in `requirements.txt`: `sqlalchemy==2.1.6`,
`psycopg==3.3.6` and `psycopg-binary==3.3.6`. `psycopg_pool` is not used,
because SQLAlchemy pools connections itself. Alembic and its dependencies
belong to BE-31.

**Actions that need the owner's explicit OK.** Approving this spec is the
standing OK for the packages above, for opening the pull request and for the
agent to pull the Postgres image and run a container on the owner's machine
(loopback only, no cost). Nothing is created or changed in Supabase by this
item: check 9 only runs `select current_user, current_setting(...)`.

**Cost.** None: the Supabase project already exists, and the local container
is free.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | SQLAlchemy 2.1.6 and psycopg 3.3.6 work together on Python 3.14 | *Assumed* | The first commit of the PR installs both and runs `make db-check`, before anything else is built on them |
| 2 | `psycopg-binary` has a wheel for Python 3.14 on macOS arm64 and on the Linux `api` image | *Assumed* | The first commit, and check 8 on the read-only image |
| 3 | The official `postgres` image accepts `POSTGRES_HOST_AUTH_METHOD=trust`, and a port published on `127.0.0.1` is not reachable from the network | *Assumed* | Check 2, and `lsof -nP -iTCP:55432` shows `127.0.0.1` |
| 4 | Supabase's direct connection is IPv6-only, so the owner's machine and the host use the **session pooler** (port 5432 on the pooler host) | *Assumed*, from memory of the documentation | Check 9. The string that works is recorded in BE-31's runbook |
| 5 | A transaction-mode pooler (port 6543) breaks prepared statements, advisory locks and DDL, so it is not used | *Assumed* | `prepare_threshold=None` is set regardless; BE-31 never uses port 6543 |
| 6 | The pooler's username format is `<role>.<project ref>` | *Assumed* | Check 9 for the owner role, and BE-31 for `app_backend` |
| 7 | The Lightsail host can reach the pooler (outbound traffic is open) | *Assumed* | BE-31, the check from the host |
| 8 | A free-plan project pauses when idle | *Assumed*, depends on the plan | The owner's answer in section 7 |

Assumptions 1 to 3 are checked in the first commit of the pull request.
Assumptions 4 to 6 can only be seen with the real project, so check 9 stays
in the item.
