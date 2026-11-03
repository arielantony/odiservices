# Runbook — Supabase database and migrations (BE-26, BE-31)

The portal has **one** Supabase project, which is production. Development uses
a local Postgres in Docker (`make db-up`). Every command in this runbook that
touches Supabase is the owner's: the agent never holds a production
credential and never reads the files named below.

| | Variable | Role | Lives on |
|---|---|---|---|
| Migrations | `PORTAL_MIGRATION_DATABASE_URL` | the owner (`postgres`) | the owner's machine, `~/.config/odiservices/supabase.env` (mode `600`) |
| The server | `PORTAL_DATABASE_URL` | `app_backend` | the host's `/etc/odiservices/.env` (root, `0600`) |

The privileged URL never goes on the host, into the image or into the
server's settings. Both URLs use the **session pooler**
(`aws-0-us-east-1.pooler.supabase.com`, port 5432), the user
`<role>.<project ref>` and `?sslmode=require`. Avoid `@ : / ? # %` in a
password, so the URL needs no escaping.

## 1. The owner URL

```sh
mkdir -p ~/.config/odiservices && umask 077
nano ~/.config/odiservices/supabase.env     # one line, single quotes:
# PORTAL_MIGRATION_DATABASE_URL='postgresql+psycopg://postgres.<PROJECT_REF>:<PASSWORD>@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require'
chmod 600 ~/.config/odiservices/supabase.env && stat -f '%Lp' ~/.config/odiservices/supabase.env
```

It must print `600`. The project ref is in *Project Settings › General*. If
the password is lost, reset it in *Project Settings › Database*.

Check the connection from `app/`:

```sh
set -a; . ~/.config/odiservices/supabase.env; set +a
PORTAL_DATABASE_URL="$PORTAL_MIGRATION_DATABASE_URL" make db-check
```

It prints `database ok (role=postgres, postgres=17)`. If it fails, the line
shows the exception class only.

## 2. The skeleton (once, before the first migration)

Proves, with something disposable, that the owner role can create roles and
schemas and that a custom role logs in through the pooler.

```sh
psql "${PORTAL_MIGRATION_DATABASE_URL/+psycopg/}"
```
```sql
create schema zz_skeleton;
create role zz_skeleton login;
\password zz_skeleton
\q
```
```sh
psql 'postgresql://zz_skeleton.<PROJECT_REF>:<PASSWORD>@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require' -Atc 'select current_user'
```

It prints `zz_skeleton`. Then, as the owner again, clean up. If anything
fails half way, these two commands are all that is left to undo:

```sql
drop schema zz_skeleton;
drop role zz_skeleton;
```

Done on 2026-11-03 (BE-31, step 1).

## 3. Apply a migration (plan, backup, apply)

Constitution, Article 7: the plan is read and approved before anything runs.

1. **Plan.** `make db-sql` prints the SQL from the start to the head and
   connects to nothing. For a database that already has revisions,
   `make db-sql FROM=<current revision>`. Read it. An approval ("apply")
   covers that SQL only; a change to it needs a new approval.
2. **Backup.** The project is on the Free plan, which has no automatic
   backups, and it is the only production database. Take a dump with a
   client of version 17 or newer, and keep the file **outside the
   repository** (it holds real data once the portal has any):

   ```sh
   mkdir -p ~/odiservices-backups
   set -a; . ~/.config/odiservices/supabase.env; set +a
   pg_dump "${PORTAL_MIGRATION_DATABASE_URL/+psycopg/}" --no-owner -Fc \
     -f ~/odiservices-backups/supabase-$(date +%Y%m%d-%H%M).dump
   ```

3. **Apply.** With the URL loaded as above:

   ```sh
   make db-upgrade && make db-current
   ```

   The first migration prints `0001 (head)`. Each migration runs in its own
   transaction, so one that fails leaves nothing half applied. A downgrade is
   refused on a remote host: production moves forward only, with a new
   migration that undoes the change.

   If a failed first migration did leave something, the owner can drop the
   schema and the role by hand after reading what is there.

## 4. The `app_backend` password and the host

The role is created with no password. Set one in `psql`, as the owner:

```sql
\password app_backend
```

It asks twice and writes nothing to the history, a file or a log.

Then build the server URL: the same pooler host, the user
`app_backend.<PROJECT_REF>`, that password and `?sslmode=require`. Check it
from your machine (use `read -rs` so it stays out of the history):

```sh
read -rs APP_URL    # paste the whole URL, then Enter
PORTAL_DATABASE_URL="$APP_URL" make db-check          # role=app_backend
```

Put it on the host **without removing what is already in the file** (the
Access settings from section 7.6 of `lightsail.md` live there). Write the URL
to a private file on your machine, then append it; the `<` is opened on your
machine, because a `<` after `sudo` on the host fails:

```sh
(umask 077; printf 'PORTAL_DATABASE_URL=%s\n' "$APP_URL" > ~/.config/odiservices/portal-db.env)
unset APP_URL
ssh -i <SSH_KEY_FILE> -o IdentitiesOnly=yes deploy@<public_ip> \
  'sudo tee -a /etc/odiservices/.env >/dev/null && sudo grep -c "^PORTAL_DATABASE_URL=" /etc/odiservices/.env' \
  < ~/.config/odiservices/portal-db.env
```

It must print `1`. If it prints `2`, the line was added twice: remove the
older one with `sudo nano /etc/odiservices/.env`. Then redeploy the tag that
is running, so `deploy.sh` sees the changed file and recreates the container:

```sh
ssh -i <SSH_KEY_FILE> -o IdentitiesOnly=yes deploy@<public_ip> \
  '/opt/odiservices/app/deploy/deploy.sh <tag-or-commit> \
   && sudo docker exec odiservices-api-1 python -m server.db'
```

It prints `database ok (role=app_backend, postgres=17)`. Delete
`~/.config/odiservices/portal-db.env` afterwards. The server starts without
the setting too, so nothing else changes.

## 5. Checks of the owner (BE-31)

Run them in this order, after the plan is approved.

| # | Command | Expected |
|---|---|---|
| 10 | Section 3, steps 2 and 3 | `0001 (head)` |
| 11 | In `psql`: `select has_schema_privilege('anon','portal','usage'), has_schema_privilege('authenticated','portal','usage')` | `f\|f` |
| 13 | Section 4, the `db-check` with the app URL | `database ok (role=app_backend, postgres=17)` |
| 14 | As `app_backend` in `psql`: `show statement_timeout` | `15s` |
| 15 | As `app_backend`: `create table portal.zz_probe (id int)` | `permission denied for schema portal` |
| 16 | Section 4, the deploy and `python -m server.db` on the host | `database ok (role=app_backend, postgres=17)` |
| 17 | `sudo docker exec odiservices-api-1 env \| grep -c '^PORTAL_DATABASE_URL='` and the same with `PORTAL_MIGRATION_DATABASE_URL` | `1` and `0` |

## 6. A new table (every later migration)

1. `make db-up && make db-upgrade`, then add the model in `server/db/`.
2. `make db-revision M="<slug>"` drafts the migration against the local
   Postgres. **Read and edit it:** a rename appears as drop plus add, and
   defaults, enums and check constraints can be missed.
3. In the migration that creates the table, call
   `enable_backend_only_rls("<table>")` from `migrations/helpers.py`. Nothing
   else is needed for the grants: the default privileges of the baseline give
   `app_backend` read and write on every new table in `portal`. Those defaults
   belong to the role that runs the migrations (the user in
   `PORTAL_MIGRATION_DATABASE_URL`). **Always migrate with that same role.** A
   table made by another role gets no grant, and the server fails with
   `permission denied`; `make test-db` reports it.
4. `make test-db`: the RLS invariant and the drift test fail when a table
   escapes the rule or the models and the migrations differ.
