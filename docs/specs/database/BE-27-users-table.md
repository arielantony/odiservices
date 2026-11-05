# Spec — BE-27 Create the `users` table

| | |
|---|---|
| **Backlog** | Platform › Database › BE-27 |
| **Depends on** | BE-31 (and through it BE-26) |
| **Spec status** | Approved (2026-11-04), with the answers in section 6. The owner confirmed the Access `sub` as the key |
| **Date** | 2026-11-04 |

## 1. Goal

The portal gets its first table: `portal.users`, one row per person who signs
in. It is minimal on purpose (owner, BACKLOG note for BE-27: "there are no
multiple users yet, but the owner wants the table now and roles later"). It
holds who the person is and nothing about what they may do, so a `roles` and
a `user_roles` table can be added later (BE-34) without reworking it.

This item is also the first one to follow the BE-31 rule for a new table
(the `portal` schema, RLS on, one policy for `app_backend`) and the first to
add a model to `Base`. It creates the table and the model. It creates no row
and no code that reads or writes one: resolving the Access identity to a row
is BE-24.

## 2. Scope

**In scope**

- The ORM model `User` in `server/db/models.py`.
- Migration `0002_users`: the table, its constraints, and the call to
  `enable_backend_only_rls("users")`.
- Tests for the model and for the table against the local Postgres.
- Applying the migration to Supabase (the owner's commands, Article 7).

**Out of scope**

- Creating a user row, on the first login or otherwise: BE-24.
- Roles, permissions and which service a user may open: BE-34. The table has
  no role column on purpose.
- Reading the Cloudflare Access token: done in BE-23 (`AccessIdentity`).
- Any route, response or screen that shows a user.

## 3. Design

### 3.1 The columns

| Column | Type | Rules |
|---|---|---|
| `id` | `uuid` | Primary key. Default `gen_random_uuid()` in the database, which makes a **v4** UUID (owner decision, 2026-11-04). The model also sets `default=uuid.uuid4`, so a row built in Python has its id before it is flushed |
| `access_subject` | `text` | Not null, unique, not empty. The `sub` claim of the Cloudflare Access token (below) |
| `email` | `text` | Not null, unique, not empty, **lowercase** (check constraint `email = lower(email)`). The code that writes it normalizes with `strip().lower()` first (BE-24). The database refuses anything else |
| `created_at` | `timestamptz` | Not null, default `now()` |
| `updated_at` | `timestamptz` | Not null, default `now()`. The model sets `onupdate=func.now()`. There is no trigger: a change made by hand in SQL does not move it, and that is accepted |

Constraint names come from the naming convention in `server/db/base.py`:
`pk_users`, `uq_users_access_subject`, `uq_users_email`,
`ck_users_email_lowercase`, `ck_users_access_subject_not_empty` and
`ck_users_email_not_empty`.

**What `sub` is.** In a JWT (JSON Web Token), `sub` is the *subject* claim:
the identifier of the person the token was issued to. Cloudflare Access puts
the user's unique id in it. It is the right key for a user, and the email is
not: an email can change (a renamed mailbox, a new domain), while `sub` stays
the same for that person. So the row is found by `access_subject`, and the
email is data that can be updated. The email stays unique and lowercase
because it is shown and searched, and because two people must not share one
(owner decision, 2026-11-04).

**Email is not treated as PII here** (owner decision, 2026-11-04): it is stored
as plain text, with no encryption and no hashing. The logging rule is
separate and stays as it is (owner, 2026-11-04: keep the email out of logs): `CLAUDE.md` and BE-21 list emails among the things
that never go in a log, and BE-23 tests that no `@` reaches the output. The
model's `__repr__` shows the id only, so a user object printed by mistake does
not leak the email.

### 3.2 A row grants nothing

A row in `users` says *who* someone is, never *what they may do*. Two layers
decide access, and neither reads this table in this item:

1. **Cloudflare Access** decides who reaches the portal at all, with its allow
   list. A person outside it never gets a token, so they never get a row.
2. **BE-34** will decide which services a signed-in person may open. Its rule
   is default deny: a new user has no role, and no role means no service. That
   is least privilege, and it holds because the table has no permission column
   to set by accident.

BE-24 only creates a row for an identity whose token **BE-23 has already
verified**. BE-27 adds no endpoint, so there is nothing to call.

### 3.3 The migration `0002_users`

Written by hand after a draft from `make db-revision M=users` (BE-31, 3.4).
The revision id is `0002` and `down_revision` is `0001`.

- `op.create_table("users", ..., schema="portal")` with the columns and
  constraints of 3.1. Names go through `op.f(...)`, so the convention does not
  double them.
- Then `enable_backend_only_rls("users")` from `migrations/helpers.py`. The
  default privileges set by `0001` give `app_backend` read and write on the
  table with no `GRANT` here.
- The downgrade drops the table (its policy goes with it). It is tested
  locally and never run in production (BE-31, 3.4).
- No data and no password.

### 3.4 The model

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    access_subject: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    # + the three CheckConstraints, named as in 3.1
    def __repr__(self) -> str:
        return f"<User {self.id}>"
```

The exact syntax is settled when the draft is written. `server/db/__init__.py`
exports `User`. That import also registers the model on `Base.metadata`,
which `migrations/env.py` reads (assumption 3).

### 3.5 Applying to production (Article 7)

The same loop as BE-31, section 3.6, and the same rule: every command against
Supabase is the owner's, and the agent never has the credential.

0. **Backup:** `pg_dump` first, outside the repository.
1. **Plan:** `make db-sql FROM=0001` prints the SQL and connects to nothing.
   The owner reads it and says "apply". The approval covers that SQL only.
2. **Apply:** `make db-upgrade`, then `make db-current` shows `0002 (head)`.
3. **No new password and no host change.** `app_backend` and its URL already
   exist from BE-31. The server does not use the table yet, so nothing
   redeploys.

### 3.6 Steps

One step. The change is about 250 lines with the tests, under the limit of
500, so the branch is `feat/be-27-users-table`, from `origin/main`, with a PR
to `main`.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/db/models.py` | New: `User` |
| `app/api/server/db/__init__.py` | Export `User` |
| `app/api/migrations/versions/0002_users.py` | New |
| `app/api/tests/test_user_model.py` | New: model tests, no database |
| `app/api/tests/test_users_db.py` | New: table tests, marked `db` |
| `docs/BACKLOG.md` | BE-27: spec link, status, PR links |

## 4. Verification

Every check runs when the item merges. Checks marked *Owner* are the owner's:
the agent never has a production credential.

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass, the BE-31 ones included (the RLS invariant and the drift test now cover a real table) |
| 3 | `make db-up && make db-upgrade && make db-current` | `0002 (head)`. Running `make db-upgrade` again changes nothing |
| 4 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select column_name\|\|':'\|\|data_type\|\|':'\|\|is_nullable from information_schema.columns where table_schema='portal' and table_name='users' order by ordinal_position"` | Five lines: `id:uuid:NO`, `access_subject:text:NO`, `email:text:NO`, `created_at:timestamp with time zone:NO`, `updated_at:timestamp with time zone:NO` |
| 5 | `psql ... -Atc "select relrowsecurity from pg_class where oid='portal.users'::regclass"` and `psql ... -Atc "select policyname\|\|'='\|\|array_to_string(roles,',') from pg_policies where tablename='users'"` | `t`, and `backend_only=app_backend` |
| 6 | `psql ... -Atc "insert into portal.users (access_subject, email) values ('sub-fulano', 'FULANO@exemplo.com')"` | `violates check constraint "ck_users_email_lowercase"` |
| 7 | `psql ... <<'SQL'` with `begin; insert ... ('sub-fulano','fulano@exemplo.com'); insert ... ('sub-fulano','outro@exemplo.com');`, then a second block with the same email and another sub `SQL` | `duplicate key value violates unique constraint "uq_users_access_subject"`, and then `"uq_users_email"` |
| 8 | `psql ... <<'SQL'` `begin; insert into portal.users (access_subject, email) values ('sub-fulano','fulano@exemplo.com') returning substr(id::text,15,1); rollback; SQL` | `4`: a version 4 UUID, and the rollback leaves no row |
| 9 | As `app_backend`: `psql postgresql://app_backend@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.users"`, then `... -Atc "drop table portal.users"` | `0`, then `must be owner of table users`: the server role reads and writes rows and cannot change the schema |
| 10 | `make db-downgrade` (one step), then `psql ... -Atc "select to_regclass('portal.users')"`, then `make db-upgrade` | An empty line (the table is gone), then `0002 (head)` again |
| 11 | *Owner:* `pg_dump`, then read `make db-sql FROM=0001` and answer "apply" | The SQL creates `portal.users`, its constraints, turns RLS on and adds one policy. No password, no data, nothing outside `portal` |
| 12 | *Owner:* with the owner URL: `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-upgrade && make db-current` | `0002 (head)` |
| 13 | *Owner:* in `psql` as the owner: `select relrowsecurity, has_table_privilege('anon','portal.users','select'), has_table_privilege('authenticated','portal.users','select') from pg_class where oid='portal.users'::regclass` | `t\|f\|f` |
| 14 | *Owner:* in `psql` as `app_backend` through the pooler: `select count(*) from portal.users`, then `show statement_timeout` | `0`, then `15s`. This also settles BE-31 assumption 10: the default privileges reach a table the migration role created |

## 5. Tests

`app/api/tests/`. Obviously fictitious data only (`fulano@exemplo.com`,
`sub-fulano`). Nothing connects to Supabase. The tests marked `db` need the
local Postgres and run in `make test-db`, each in a throwaway database, like
the BE-31 tests (they reuse its fixtures).

`test_user_model.py`

| Test | Asserts |
|---|---|
| `test_user_is_in_the_portal_schema` | `User.__table__.schema == "portal"` and it is on `Base.metadata` |
| `test_user_id_default_is_uuid4` | `User().id` default produces a `uuid.UUID` with `version == 4` |
| `test_user_repr_shows_only_the_id` | `repr(user)` contains the id and neither the email nor the subject |
| `test_user_constraint_names` | The table's constraint names are the six in section 3.1 |

`test_users_db.py`, marked `db`

| Test | Asserts |
|---|---|
| `test_users_table_columns` | The five columns, their types and `NOT NULL`, as in check 4 |
| `test_id_default_generates_v4` | An insert with no id gets one, and its version is 4 |
| `test_timestamps_default_to_now` | `created_at` and `updated_at` are set on insert, and an ORM update moves `updated_at` |
| `test_email_must_be_lowercase` | An uppercase email fails on `ck_users_email_lowercase` |
| `test_empty_subject_and_email_rejected` | An empty `access_subject` and an empty `email` each fail their check |
| `test_subject_and_email_are_unique` | A second row with the same `access_subject`, and one with the same `email`, each fail on their unique constraint |
| `test_users_table_is_backend_only` | The RLS invariant of BE-31 holds with the table present, and `app_backend` can insert, select, update and delete a row |
| `test_app_backend_cannot_drop_users` | As `app_backend`, `DROP TABLE portal.users` fails |
| `test_upgrade_downgrade_upgrade_with_users` | `upgrade head`, `downgrade 0001`, `upgrade head` succeed, and the table exists after the last one |
| `test_models_match_migrations` | The BE-31 drift test, unchanged, still reports no difference. It now covers a real table, so it fails if `0002` and `User` disagree on a column or a constraint |

## 6. Open questions

| # | Question | Answer |
|---|---|---|
| 1 | Key the row on the Access `sub`, or on the email? | **`sub`** (confirmed by the owner when approving, 2026-11-04; explained in 3.1) |
| 2 | Is the row created on the first login, and how is privilege kept in check? | The row is created by BE-24, not here. A row grants nothing: Access is the gate and BE-34 will deny by default (3.2). The owner's question: *least privilege, yes*, held by there being no permission column |
| 3 | Email lowercase and unique? | **Yes** (owner, 2026-11-04). Enforced by the database |
| 4 | Is email PII? | **No** (owner, 2026-11-04): plain text in the table. It never goes in a log: the owner confirmed on 2026-11-04 that the rule stays (`CLAUDE.md`, BE-21) |
| 5 | The primary key? | **UUID v4** (owner, 2026-11-04) |
| 6 | May `email` be null? BE-23 accepts a token with no `email` | **Not null** (owner, 2026-11-04: "always store the email"). A person who signs in through an identity provider has one. A token with none (a service token) is not a person, so BE-24 decides what to do with it, and it gets no row. If BE-24 finds a real case, it amends this table |

A question with no answer becomes an assumption with the recommended option.

## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| BE-31 is merged and the local Postgres works | Agent | `make db-up && make db-check && make db-current` | `database ok (role=odiservices, postgres=17)` and `0001 (head)` |
| The Alembic loop works against the local database | Agent | `make db-upgrade` on a fresh `make db-up` | No error |
| `pg_dump` and `psql` on the owner's machine | Owner | `pg_dump --version && psql --version` | `pg_dump` 17 or newer, `psql` any version |
| The owner's connection string | Owner | `stat -f '%Lp' ~/.config/odiservices/supabase.env` | `600` |
| Supabase has `0001` applied | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-current` | `0001 (head)` |

**Packages.** None. SQLAlchemy, Alembic and psycopg are already pinned.

**Actions that need the owner's explicit OK.** Approving this spec is the
standing OK for the pull request. This one needs a fresh OK when it comes up:

- **Applying `0002` to Supabase** (check 11): the owner reads `make db-sql
  FROM=0001` and approves that SQL. A change to the SQL needs a new approval.

The agent never has a production credential and never connects to Supabase.

**Cost.** None. A failed migration leaves nothing behind, because each one
runs in a transaction.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `gen_random_uuid()` exists with no extension on the local Postgres 17 and on Supabase (Postgres 17.11), and returns a v4 UUID | *Assumed*, from the Postgres documentation (core since 13) | Checks 3 and 8 locally, and check 12 on Supabase (the migration would fail) |
| 2 | Alembic's autogenerate does not compare server defaults, so the drift test cannot see a wrong `server_default` (`migrations/options.py` does not turn it on) | *Verified* by reading `options.py` | `test_id_default_generates_v4` and `test_timestamps_default_to_now` test the behavior, not the metadata |
| 3 | Importing `User` in `server/db/__init__.py` puts it on `Base.metadata` before `env.py` reads it, because Python runs the package `__init__` before the `server.db.base` import in `env.py` | *Assumed* | `test_models_match_migrations`: a model that did not register shows up as a table the database has and the models lack |
| 4 | The naming convention turns `CheckConstraint(..., name="email_lowercase")` into `ck_users_email_lowercase` | *Assumed*, from the SQLAlchemy documentation | `test_user_constraint_names` and check 6 |
| 5 | The default privileges from `0001` reach a table that `0002` creates, so `app_backend` needs no `GRANT` | *Assumed* (BE-31 assumption 10 for Supabase) | `test_users_table_is_backend_only` locally, and check 14 on Supabase |
| 6 | The Access `sub` is stable for one person across logins and different for each person | *Assumed*, from the Cloudflare documentation. BE-23 check 8 already saw a real token carry a `sub` | BE-24 reads a real token and records it. This item stores the value and does not depend on its format |

Assumptions 1, 3, 4 and 5 are checked by the tests and checks of this item.
Assumption 6 does not block it: nothing here reads a token.
