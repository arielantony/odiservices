# Spec — BE-31 Version schema changes as SQL migrations

| | |
|---|---|
| **Backlog** | Platform › Database › BE-31 |
| **Depends on** | BE-26 (and through it BE-17, BE-18) |
| **Spec status** | Approved (2026-11-02) |
| **Date** | 2026-11-02 |

## 1. Goal

Every change to the database schema is a numbered migration in the
repository, applied by Alembic, the same way to the local Postgres and to the
one production project on Supabase (owner decisions, 2026-11-02: Alembic, one
production database). This item builds the machinery and the **baseline**
migration. The baseline creates the `portal` schema and the `app_backend`
role, and sets the rule that every later table follows: row level security on,
and a policy for `app_backend` only. It creates no table. The tables are
BE-27 to BE-30.

It also applies the baseline to Supabase and puts the `app_backend`
connection string on the host. That is the first change to the production
database, so it follows `docs/CONSTITUTION.md`, Article 7: the owner reads the
SQL before it runs, and every command against Supabase is the owner's.

## 2. Scope

**In scope**

- Alembic: `alembic.ini`, `migrations/env.py`, the migration template and the
  naming rule.
- `server/db/base.py`: the ORM `DeclarativeBase`, the naming convention and
  `MetaData(schema="portal")`. Alembic's `env.py` needs the metadata, so it
  lives here and BE-27 adds the first model to it.
- The baseline migration `0001`.
- A helper that every table migration calls to turn on RLS and add the policy.
- `make db-upgrade`, `db-sql`, `db-current`, `db-downgrade` and `db-revision`.
- Tests: the migration files, the baseline against a real local Postgres, the
  RLS invariant, and the test that fails when the ORM models and the migrated
  schema differ.
- The runbook for Supabase: the owner role, applying, the `app_backend`
  password, the connection string, the host.
- Pinning Alembic and its dependencies.

**Out of scope**

- The tables and the categories: BE-27 to BE-30.
- The users' roles and the services they may use: BE-34. (`app_backend` is a
  *database* role, the one the server connects as. It has nothing to do with
  the portal's user roles.)
- Running migrations from the host, from the `api` image or on deploy. They
  run from the owner's machine only (section 3.5).
- Moving the connection string to a secrets manager: OPS-05.

## 3. Design

### 3.1 One schema, one role, RLS with a policy

The earlier plan, "RLS on with no policy" together with "the server connects
as `app_backend`", was wrong: a role that does not own the table and has no
`BYPASSRLS` sees zero rows when RLS is on and no policy applies to it. The
design is this.

| Layer | What it does |
|---|---|
| **Schema `portal`** | Every table lives here, never in `public`. Supabase's HTTP API exposes `public` by default and not `portal`, so a mistaken policy still does not publish a table |
| **No access for the API roles** | `anon` and `authenticated` get no `USAGE` on `portal`. They do not exist in the local Postgres, so the migration revokes from them only when they exist |
| **RLS on every table** | `ENABLE ROW LEVEL SECURITY` |
| **One policy, for `app_backend`** | `CREATE POLICY backend_only ON <table> TO app_backend USING (true) WITH CHECK (true)`. The server sees everything and decides per user in code. No other role has a policy, so they see nothing |
| **`app_backend` is a plain role** | `LOGIN`, no superuser, no `BYPASSRLS`, no `CREATEDB`, no `CREATEROLE`, no ownership of tables. It can read and write rows and cannot change the schema |

The migration role (`postgres` on Supabase, `odiservices` locally) owns the
tables and so is not limited by RLS. It is used by the owner for migrations
only (section 3.5).

### 3.2 The baseline migration `0001`

Plain SQL through `op.execute`, in one transaction:

1. `CREATE SCHEMA IF NOT EXISTS portal`.
2. `CREATE ROLE app_backend` when it does not exist, with `LOGIN NOSUPERUSER
   NOBYPASSRLS NOCREATEDB NOCREATEROLE`. **No password**: a password in a
   migration would be in the repository. A `LOGIN` role with no password
   cannot authenticate with a password, so it cannot be used until the owner
   sets one (section 3.6). Locally the Postgres trusts loopback (BE-26), so
   the role works with no password.
3. `REVOKE ALL ON SCHEMA portal FROM PUBLIC`, then `GRANT USAGE ON SCHEMA
   portal TO app_backend`.
4. `ALTER DEFAULT PRIVILEGES IN SCHEMA portal GRANT SELECT, INSERT, UPDATE,
   DELETE ON TABLES TO app_backend`, and `USAGE, SELECT ON SEQUENCES`. The
   defaults apply to what the migration role creates later, so a table
   migration needs no grant of its own.
5. `REVOKE ALL ON SCHEMA portal FROM anon, authenticated`, inside a `DO` block
   that runs only when those roles exist.
6. `ALTER ROLE app_backend SET statement_timeout = '15s'` and
   `idle_in_transaction_session_timeout = '30s'`. A setting on the role holds
   for every connection it opens, with no help from the client.

Alembic's own table, `portal.alembic_version`, is created before `0001` runs,
so the defaults of step 4 do not reach it: `app_backend` cannot read it. A
test says so.

The downgrade reverses the grants, the default privileges and the role's
settings. It does **not** drop the role, because a role belongs to the whole
Postgres server and a second local database may still use it. It does **not**
drop the schema either: `env.py` creates `portal` for Alembic's own version
table, which lives in it, so dropping it mid-downgrade would break Alembic's
last step. (Found while building step 2.)

### 3.3 The helper for every table

`migrations/helpers.py` has `enable_backend_only_rls(table: str)`, which runs
`ALTER TABLE portal.<table> ENABLE ROW LEVEL SECURITY` and creates the policy
of 3.1. Every table migration (BE-27 on) calls it. A test (section 5) fails
when a table in `portal` has no RLS or has a policy for any role other than
`app_backend`, so forgetting the call is caught before the merge.

### 3.4 Migration files

- Alembic, with `--autogenerate` as a **drafting aid** only (decided by the
  owner, 2026-11-02). `make db-revision M="<slug>"` runs `alembic revision
  --autogenerate` against the local Postgres and writes a draft for tables,
  columns, indexes and constraints. The author **reads and edits every
  draft** before committing it: a rename appears as drop plus add (data loss),
  and server defaults, enums and check constraints may be missed. Autogenerate
  does not see RLS, policies, grants or roles, so those are written by hand:
  the helper (3.3) in each migration that creates a table, and the baseline
  for roles and privileges. The invariant test is the safety net for a
  forgotten helper call. The `db-sql` plan (3.6) is what the owner approves,
  never the draft.
- Revision ids are `0001`, `0002`, and so on, in a straight line: one head,
  no branches. The file name is `<id>_<slug>.py`.
- Each migration runs in its own transaction (`transaction_per_migration`),
  so one that fails leaves nothing half-applied.
- Every migration has a `downgrade`. It is written and tested on the local
  Postgres and **never run in production**: `env.py` refuses a downgrade when
  the host is not loopback.
- No password, no key and no real data in a migration.
- Alembic takes no lock on Postgres. One operator runs the migrations, so two
  at once is not a case this item handles.

### 3.5 Where migrations run, and with which credential

| | Migrations | The server |
|---|---|---|
| Variable | `PORTAL_MIGRATION_DATABASE_URL` | `PORTAL_DATABASE_URL` (BE-26) |
| Role | the owner (`postgres` on Supabase) | `app_backend` |
| Read by | `migrations/env.py`, from the environment, never from `Settings` | the server |
| Lives on | the owner's machine (`~/.config/odiservices/supabase.env`, mode 600) | the host's `/etc/odiservices/.env` |

The privileged credential never goes on the host, into the image or into the
server's settings. The agent never has either production credential: every
command against Supabase in this item is the owner's.

`env.py` applies the BE-26 rules to the migration URL (a remote host needs
TLS), reads nothing else from the repository's settings, and creates the
schema `portal` before Alembic creates its version table there
(`version_table_schema="portal"`).

### 3.6 Applying to production (Article 7)

0. **Backup.** The Supabase project is on the Free plan, which has no
   automatic backups, and it is the only production database. Before each
   `upgrade` the owner runs `pg_dump` against it (the owner's URL) and keeps
   the file **outside the repository**. The dump holds real data once the
   portal has any, so it stays on the owner's machine and is never committed
   or shared.
1. **Plan.** `make db-sql` runs `alembic upgrade --sql`: it prints the SQL
   from the current revision to the head and **connects to nothing**. The
   owner reads it and says "apply". An approval covers that SQL only. For a
   production database that already has `0001`, `make db-sql FROM=0001`.
2. **Apply.** The owner runs `make db-upgrade` with the owner's URL, then
   `make db-current`.
3. **The `app_backend` password.** The owner opens `psql` on Supabase and runs
   `\password app_backend`, which asks for the password twice and never puts
   it in the history, a file or a log. The owner then builds the server's URL
   (through the **session pooler**, the user `app_backend.<project ref>`,
   `sslmode=require`) and writes it in the host's `/etc/odiservices/.env`
   (`docs/deploy/lightsail.md`, 7.6 pattern). `deploy.sh` recreates the
   container because the file's hash changed (#58).
4. **Check.** `python -m server.db` inside the container must print
   `role=app_backend`.

### 3.7 Steps

The item comes to about 600 changed lines with the tests, over the limit of
500, so it has two steps and a final pull request, on the feature branch
`feature/be-31-migrations`.

| Step | Contents | Lines |
|---|---|---|
| 1, the machinery | `alembic` pinned, `alembic.ini`, `migrations/env.py` and the template, `server/db/base.py`, the four Make targets, the migration-file tests and the guard tests. No migration yet | about 300 |
| 2, the baseline | `0001`, `helpers.py`, the database tests: baseline, privileges, the RLS invariant and the drift test | about 300 |
| Final PR | `feature/be-31-migrations` to `main`: the runbook (`docs/deploy/supabase.md`), the BE-26, BE-27 and BE-34 notes, BE-31 Done, and the live checks (owner) | docs only |

Step 1 also holds the **skeleton** of Article 7 (rule 6): before the real
baseline is written, the owner proves the loop on Supabase with something
disposable (check 12), so a wrong assumption about roles or the pooler shows
up while it costs nothing.

### 3.8 Files

| File | Change | Step |
|---|---|---|
| `app/api/requirements-dev.in`, `requirements-dev.txt` | Add `alembic`, compiled with `uv pip compile` (dev only, not in the image) | 1 |
| `app/api/alembic.ini` | New | 1 |
| `app/api/migrations/env.py`, `script.py.mako` | New | 1 |
| `app/api/server/db/base.py` | New: `Base`, the naming convention, `MetaData(schema="portal")` | 1 |
| `app/Makefile` | `db-upgrade`, `db-sql`, `db-current`, `db-downgrade`, `db-revision`, `help` lines | 1 |
| `app/api/migrations/versions/0001_baseline.py` | New | 2 |
| `app/api/migrations/helpers.py` | New: `enable_backend_only_rls` | 2 |
| `docs/specs/database/BE-26-postgres-connection.md` | Out-of-scope line: the base class is BE-31's, not BE-27's | final |
| `docs/deploy/supabase.md` | New runbook: the owner role, the skeleton, plan and apply, the password, the URLs, the host | final |
| `docs/BACKEND_GUIDELINES.md` | Data section: migrations, the `portal` schema, the rule for a new table | final |
| `docs/BACKLOG.md` | BE-31 status and PR links; the BE-27 note (it adds the first model, not the base) | each |

## 4. Verification

Every check runs when the item merges. Checks marked *Owner* are the owner's:
the agent never has a production credential. Checks 9 to 17 are the owner's
and need the pooler details (section 7); the item is not Done without them.

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass: the baseline, the privileges, the RLS invariant and the drift test |
| 3 | `make db-up && make db-upgrade && make db-current` | `0001 (head)`. Running `make db-upgrade` again changes nothing |
| 4 | `make db-down && make db-sql \| tee "$SCRATCH/plan.sql" \| grep -c 'CREATE SCHEMA'` | `1` or more, with Postgres stopped: the plan needs no connection. `grep -ci 'password' "$SCRATCH/plan.sql"` prints `0` |
| 5 | `PORTAL_MIGRATION_DATABASE_URL='postgresql+psycopg://u@db.example.com/x?sslmode=require' make db-downgrade` | Refuses, naming the rule, before connecting |
| 6 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select rolsuper, rolbypassrls from pg_roles where rolname='app_backend'"` | `f\|f` |
| 7 | `PORTAL_DATABASE_URL=postgresql+psycopg://app_backend@127.0.0.1:55432/odiservices make db-check` | `database ok (role=app_backend, postgres=17)` |
| 8 | `git grep -niE "password\s+'" -- app/api/migrations` and the BE-26 check 10 | No match |
| 9 | *Owner:* read `make db-sql` (from `0001`, if applied already) and answer "apply" | The SQL has no password and touches only `portal` and the role. An approval covers that SQL only |
| 10 | *Owner:* with the owner URL in `supabase.env`: `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-upgrade && make db-current` | `0001 (head)` |
| 11 | *Owner:* in `psql` as the owner: `select has_schema_privilege('anon','portal','usage'), has_schema_privilege('authenticated','portal','usage')` | `f\|f`: the Supabase HTTP API has no access to `portal` |
| 12 | *Owner, skeleton (step 1):* in `psql` as the owner, create the schema `zz_skeleton` and the role `zz_skeleton` with a password (typed at the `\password` prompt), then log in through the session pooler as `zz_skeleton.<project ref>` and run `select current_user`, then drop both | `zz_skeleton`, and `\dn` and `\du` show neither afterwards. This proves the owner role may create roles and schemas, and that a custom role logs in through the pooler with that user name |
| 13 | *Owner:* `\password app_backend`, then with the new URL on the Mac: `PORTAL_DATABASE_URL='<the app URL>' make db-check` | `database ok (role=app_backend, postgres=<major>)` |
| 14 | *Owner:* as `app_backend`: `show statement_timeout` | `15s`: the role's settings hold through the pooler |
| 15 | *Owner:* as `app_backend`: `create table portal.zz_probe (id int)` | `permission denied for schema portal`: the server role cannot change the schema |
| 16 | *Owner:* put the URL in the host's `/etc/odiservices/.env`, run `deploy.sh <tag>`, then `sudo docker exec odiservices-api-1 python -m server.db` | `database ok (role=app_backend, postgres=<major>)`: the host reaches the pooler |
| 17 | *Owner:* `sudo docker exec odiservices-api-1 env \| grep -c '^PORTAL_DATABASE_URL='` and `sudo docker exec odiservices-api-1 env \| grep -c '^PORTAL_MIGRATION_DATABASE_URL='` | `1` and `0`: the privileged credential is not on the host |
| 18 | After check 3, add a scratch model with one column to a throwaway copy of `Base`, then `make db-revision M=probe` | A draft file appears in `migrations/versions/` with the table. It is deleted afterwards, and `git status` is clean |

## 5. Tests

`app/api/tests/`. `make test-api` needs no Docker. The tests marked `db` need
the local Postgres and run in `make test-db`; each one creates a throwaway
database on it and drops it. Nothing connects to Supabase.

`test_migration_files.py`

| Test | Asserts |
|---|---|
| `test_single_head` | Alembic's script directory has exactly one head |
| `test_revision_ids_are_sequential` | `0001`, `0002`, ... with no gap, and the file name starts with the id |
| `test_every_migration_has_a_downgrade` | Each file defines `downgrade`, and it does not just `pass` |
| `test_no_password_literal` | No migration contains `PASSWORD '` (case-insensitive) or a connection string |

`test_migration_guards.py`

| Test | Asserts |
|---|---|
| `test_migration_url_required` | No `PORTAL_MIGRATION_DATABASE_URL`: a clear error that names the variable |
| `test_migration_url_remote_needs_tls` | The BE-26 TLS rule applies, and the error does not print the value |
| `test_downgrade_refused_on_remote_host` | The guard refuses before any connection. A loopback host is allowed |
| `test_make_db_sql_needs_no_database` | The offline command succeeds with Postgres stopped (invoked with no URL set) |

`test_migrations_db.py`, marked `db`

| Test | Asserts |
|---|---|
| `test_upgrade_downgrade_upgrade` | `upgrade head`, `downgrade base`, `upgrade head` succeed on an empty database |
| `test_baseline_creates_schema_and_role` | `portal` exists. `app_backend` has `rolcanlogin` and none of superuser, `BYPASSRLS`, `CREATEDB` or `CREATEROLE` |
| `test_app_backend_cannot_change_the_schema` | As `app_backend`, `CREATE TABLE portal.x` and `DROP SCHEMA portal` fail |
| `test_app_backend_cannot_read_version_table` | As `app_backend`, `select * from portal.alembic_version` fails |
| `test_role_settings` | `statement_timeout` and `idle_in_transaction_session_timeout` are set on the role |
| `test_rls_invariant_holds` | Every table in `portal` has RLS on and exactly one policy, for `app_backend` |
| `test_rls_invariant_detects_a_bad_table` | A scratch table without RLS, and another with a policy for `PUBLIC`, make the invariant check fail, so the check is known to be able to fail |
| `test_helper_enables_rls_and_policy` | `enable_backend_only_rls` on a scratch table gives RLS on and the one policy, and `app_backend` can read and write it |
| `test_models_match_migrations` | Alembic's `compare_metadata` of `Base.metadata` against the migrated database reports no difference |
| `test_drift_check_detects_a_difference` | A scratch model with a column the database lacks makes the same comparison report a difference |

## 6. Open questions

| # | Question | Recommended |
|---|---|---|
| 1 | Write a `downgrade` for every migration? | **Yes**, tested locally and refused on a remote host. It lets a developer reset the local database and proves each migration can be reversed in a test. Production moves forward only |
| 2 | Put the timeouts on the role (`statement_timeout` 15 s, `idle_in_transaction_session_timeout` 30 s)? | **Yes.** A runaway query or a forgotten transaction cannot hold the pooler. If a check shows the pooler ignores role settings, the values move to the engine |
| 3 | Grants: default privileges for the schema, or an explicit `GRANT` in each table migration? | **Default privileges plus the invariant test.** One place sets them, and a test catches a table that escapes |
| 4 | Is `alembic upgrade --sql` the "plan" the owner approves? | **Yes.** It prints exactly what will run and needs no connection, the equivalent of `tofu plan` here |

A question with no answer becomes an assumption with the recommended option.

## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| BE-26 is merged and the local Postgres works | Agent | `make db-up && make db-check` | `database ok (role=odiservices, postgres=17)` |
| The packages resolve for Python 3.14 | Agent | `printf 'alembic\n' > "$SCRATCH/in.txt" && uv pip compile --python-version 3.14 "$SCRATCH/in.txt"` | `alembic`, `mako`, `markupsafe`, `sqlalchemy`, `typing-extensions` (run 2026-11-02: alembic 1.20.1, mako 1.4.3, markupsafe 3.0.4) |
| Supabase project details | Owner | Read in the dashboard | **Received 2026-11-02:** region `us-east-1`, Postgres 17.11, Free plan. Still to confirm in the dashboard: the session pooler host, and the pooler user format (assumption 6). Checks 9 to 17 are the owner's to run |
| `pg_dump` on the owner's machine, version 17 or newer | Owner | `pg_dump --version` | A version number of 17 or newer (a dump needs a client at least as new as the server) |
| The owner's connection string, as in BE-26 | Owner | `stat -f '%Lp' ~/.config/odiservices/supabase.env` | `600` |
| The owner role can create roles and schemas | Owner | `psql "${PORTAL_MIGRATION_DATABASE_URL/+psycopg/}" -Atc "select rolcreaterole from pg_roles where rolname=current_user"` | `t` |
| `psql` on the owner's machine | Owner | `psql --version` | A version number (14 is installed) |
| SSH access to the host (check 16) | Owner | `ssh -i <SSH_KEY_FILE> deploy@<public_ip> true; echo $?` | `0` |

**Packages this item installs** (and only these), pinned by `uv pip compile`
in `requirements-dev.txt` (the file the `api` image does not install):
`alembic==1.20.1`, `mako==1.4.3` and `markupsafe==3.0.4`. SQLAlchemy and
`typing-extensions` are already pinned by BE-26.

**Actions that need the owner's explicit OK.** Approving this spec is the
standing OK for the packages above and for the pull requests. Each of these
needs a fresh OK, asked when it comes up:

- **Applying any migration to Supabase.** The owner reads the output of
  `make db-sql` first and approves that SQL (check 9). A change to the SQL
  needs a new approval.
- **Setting the `app_backend` password and editing the host's `.env`.** Done by
  the owner, with their own commands.

The agent never has a production credential, never reads `supabase.env` or the
host's `.env`, and never connects to Supabase.

**Cost.** None. The project exists. A failed migration leaves nothing behind,
because each one runs in a transaction. A failed skeleton (check 12) leaves a
role and a schema the owner drops with two commands (the runbook lists them).

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | Alembic 1.20.1 works with SQLAlchemy 2.1.6 and psycopg 3 on Python 3.14 | *Assumed* | The first commit of step 1 installs them and runs `alembic --version` and `make db-current` |
| 2 | `alembic upgrade --sql` (offline) prints the SQL of `op.execute` and of the version table, with no connection | *Assumed* | Check 4, in step 1 once `env.py` exists |
| 3 | `version_table_schema="portal"` works when `env.py` creates the schema first, in online and offline mode | *Assumed* | Checks 3 and 4 |
| 4 | The Supabase owner role may `CREATE ROLE` and `CREATE SCHEMA` | *Assumed* | Check 12 (the skeleton) |
| 5 | A custom role logs in through the session pooler as `<role>.<project ref>` | *Assumed* | Check 12 |
| 6 | Role-level settings (`ALTER ROLE ... SET`) apply to connections through the pooler | *Assumed* | Check 14 |
| 7 | Supabase's HTTP API exposes only the schemas set in its settings (by default `public`), so `portal` is not exposed | *Assumed*, from the documentation | Check 11 proves the privileges. The owner can also read Settings › API › Exposed schemas |
| 8 | Supabase grants `anon` and `authenticated` nothing on a new schema | *Assumed* | Check 11 |
| 9 | `app_backend` cannot read `portal.alembic_version`, because the version table exists before the default privileges are set | *Assumed* | `test_app_backend_cannot_read_version_table` |
| 10 | The migration role keeps the same name for the whole life of the project (default privileges apply to objects that role creates) | *Assumed* | Check 15 after the first table (BE-27) |

Assumptions 1 to 3 are checked in the first commit of step 1. Assumptions 4
to 8 can only be seen with the real project, so the skeleton (check 12) runs
in step 1, before the baseline is written.
