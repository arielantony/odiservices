# Spec — BE-28 Create the `statements` table

| | |
|---|---|
| **Backlog** | Platform › Database › BE-28 |
| **Depends on** | BE-27 (Done), BE-31 (Done) |
| **Spec status** | In review (2026-11-10). Not Ready until the owner approves it |
| **Date** | 2026-11-10 |

## 1. Goal

The portal stores one row per card statement (fatura) a person sends:
`portal.statements`. A statement belongs to a user and carries the total the
bank printed (`total_lanc_atuais`), which the import (BE-05) compares with the
sum of the transactions. This item creates the table and the model. It creates
no row and no code that reads or writes one. The transactions are BE-29, which
refers to this table by a foreign key.

## 2. Scope

**In scope**

- The table `portal.statements` and its migration `0004_statements`.
- The ORM model `Statement` in `server/db/models.py`.
- Tests against the local Postgres (section 5).

**Out of scope**

- The transactions and their foreign key to this table: BE-29.
- Processing status and failure reason: BE-07 adds those columns.
- Card name and last digits: BE-09 adds those columns.
- Creating a statement, validating the sum, listing, deleting: BE-05, BE-06,
  BE-15. No route here.
- Keeping the uploaded PDF: BE-04. This table stores no file and no file
  content.
- Who may see which statement: the server filters by `user_id` in every query
  (BE-06, BE-10). The database policy stays the one of BE-31 (3.2).

## 3. Design

### 3.1 The columns

| Column | Type | Rules |
|---|---|---|
| `id` | `uuid` | Primary key. Default `gen_random_uuid()`; the model also sets `default=uuid.uuid4`, as `users` does |
| `user_id` | `uuid` | Not null. Foreign key to `portal.users(id)`, `ON DELETE RESTRICT` (question 2). The owner of the statement |
| `name` | `text` | Not null, not empty. What the list shows ("Fatura Cartão Exemplo, set/2026"). Filled by BE-03 and BE-05 (question 3) |
| `total_lanc_atuais` | `numeric(14,2)` | Nullable (question 1). The total of the current charges, in BRL, as printed. Money is `numeric`, never a float |
| `created_at` | `timestamptz` | Not null, default `now()`. This is the "date sent" of the list (FE-04) |
| `updated_at` | `timestamptz` | Not null, default `now()`. The model sets `onupdate=func.now()`. No trigger, as in `users` |

Constraint names come from the convention in `server/db/base.py`:
`pk_statements`, `fk_statements_user_id_users`, `ck_statements_name_not_empty`.

One index: `ix_statements_user_id_created_at` on `(user_id, created_at DESC)`,
for "the current user's statements, newest first" (BE-06). It also serves the
foreign key. Created with the table; the model declares it, so the drift test
sees it.

The total has no sign check: a credit or a refund can make a statement total
negative, and rejecting it would break a real statement.

### 3.2 Access and RLS

`enable_backend_only_rls("statements")` as for every table. `app_backend`
reads and writes it, through the default privileges of `0001`, with no
`GRANT`. The policy does not filter by user. That filter is code (`where
user_id = :current`) in BE-06 and BE-10, and each of those items tests that
one user cannot read another's statement. Row-level policy per user is not
used because the server connects as one role for every user.

### 3.3 The migration `0004_statements`

Written by hand after a draft from `make db-revision M=statements`.
`down_revision` is `0003`.

- `op.create_table("statements", ..., schema="portal")` with the columns,
  constraints and the foreign key of 3.1, names through `op.f(...)`.
- `op.create_index` for `ix_statements_user_id_created_at`.
- `enable_backend_only_rls("statements")`.
- The downgrade drops the table. Tested locally, never run in production
  (BE-31, 3.4).
- No data.

### 3.4 The model

```python
class Statement(Base):
    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint("name <> ''", name="name_not_empty"),
        Index("ix_statements_user_id_created_at", "user_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(Text)
    total_lanc_atuais: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Statement {self.id}>"
```

The exact syntax is settled when the draft is written. `__repr__` shows the id
only: the name can reveal a card or a month. `server/db/__init__.py` exports
`Statement`.

### 3.5 Applying to production (Article 7)

Same loop as BE-30, section 3.5, and the same rule: every command against
Supabase is the owner's.

0. **Backup:** `scripts/db-backup.sh` before the change.
1. **Plan:** `make db-sql FROM=0003` prints the SQL and connects to nothing.
   The owner reads it and says "apply". The approval covers that SQL only.
2. **Apply:** `make db-upgrade`, then `make db-current` shows `0004 (head)`.
3. **No redeploy.** Nothing in the running server reads the table yet.

### 3.6 Steps

One step, about 250 lines with the tests. Branch `feat/be-28-statements-table`,
from `origin/main`, PR to `main`.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/db/models.py` | New: `Statement` |
| `app/api/server/db/__init__.py` | Export `Statement` |
| `app/api/migrations/versions/0004_statements.py` | New |
| `app/api/tests/test_statement_model.py` | New: model tests, no database |
| `app/api/tests/test_statements_db.py` | New: table tests, marked `db` |
| `docs/BACKLOG.md` | BE-28: spec link, status, PR links |

## 4. Verification

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass, the earlier ones included (the RLS invariant and the drift test now cover this table) |
| 3 | `make db-upgrade && make db-current` on the local database | `0004 (head)`. A second `make db-upgrade` changes nothing |
| 4 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select column_name\|\|':'\|\|data_type\|\|':'\|\|is_nullable from information_schema.columns where table_schema='portal' and table_name='statements' order by ordinal_position"` | Six lines: `id:uuid:NO`, `user_id:uuid:NO`, `name:text:NO`, `total_lanc_atuais:numeric:YES`, `created_at:timestamp with time zone:NO`, `updated_at:timestamp with time zone:NO` |
| 5 | `psql ... -Atc "select relrowsecurity from pg_class where oid='portal.statements'::regclass"` | `t` |
| 6 | `psql ... -Atc "insert into portal.statements (user_id, name) values (gen_random_uuid(), 'Fatura Cartão Exemplo, set/2026')"` | `violates foreign key constraint "fk_statements_user_id_users"` |
| 7 | `psql ... -Atc "select indexdef from pg_indexes where indexname='ix_statements_user_id_created_at'"` | One line, on `(user_id, created_at DESC)` |
| 8 | `make db-downgrade`, then `psql ... -Atc "select to_regclass('portal.statements')"`, then `make db-upgrade` | An empty line, then `0004 (head)` again |
| 9 | *Owner:* `scripts/db-backup.sh`, then read `make db-sql FROM=0003` and answer "apply" | The SQL creates `portal.statements`, its constraints and index, turns RLS on, adds one policy. No password, no data, nothing outside `portal` |
| 10 | *Owner:* `make db-upgrade && make db-current` against Supabase | `0004 (head)` |
| 11 | *Owner:* in `psql` as the owner: `select count(*) from portal.statements;` | `0` |

Checks 9 to 11 need the owner's production database. They are not optional:
the item is Done when they pass.

## 5. Tests

Fictitious data only (`sub-fulano`, `fulano@exemplo.com`, "Fatura Cartão
Exemplo, set/2026"). The `db` tests reuse the BE-31 fixtures and run in
`make test-db`.

`test_statement_model.py`

| Test | Asserts |
|---|---|
| `test_statement_is_in_the_portal_schema` | `Statement.__table__.schema == "portal"` and it is on `Base.metadata` |
| `test_statement_id_default_is_uuid4` | The column default makes a `uuid.UUID` of version 4 |
| `test_statement_repr_shows_only_the_id` | `repr` has the id and not the name |
| `test_statement_total_is_numeric_and_nullable` | The column is `Numeric(14, 2)` and nullable |

`test_statements_db.py`, marked `db`

| Test | Asserts |
|---|---|
| `test_statements_columns` | The six columns, types and nullability, as in check 4 |
| `test_defaults_are_set_on_insert` | With only `user_id` and `name`, the row gets an `id` (version 4), `created_at` and `updated_at`, and `total_lanc_atuais` is null. Tested directly because the drift test cannot see defaults (BE-35) |
| `test_updated_at_moves_on_orm_update` | An ORM update changes `updated_at` |
| `test_empty_name_is_refused` | An empty `name` raises `IntegrityError` on `ck_statements_name_not_empty` |
| `test_unknown_user_is_refused` | A `user_id` with no user raises `IntegrityError` on the foreign key |
| `test_user_with_statements_cannot_be_deleted` | Deleting a user that has a statement fails (`RESTRICT`) |
| `test_total_keeps_two_decimals` | `11906.35` is stored and read back as `Decimal("11906.35")`, and a negative total is accepted |
| `test_app_role_reads_and_writes_statements` | As `app_backend`, insert, select, update and delete work |
| `test_app_role_cannot_drop_statements` | As `app_backend`, `DROP TABLE portal.statements` fails |
| `test_downgrade_drops_the_table` | `downgrade 0003` removes the table, `upgrade head` brings it back |
| `test_models_match_migrations` | The BE-31 drift test still reports no difference. It sees the columns, the foreign key and the index |

## 6. Open questions

Each with a recommended option. A question with no answer becomes an
assumption with the recommended option.

1. **Is `total_lanc_atuais` nullable?** *Recommended: yes.* The list (FE-04)
   shows statements still being classified or failed, with "—" as the total,
   and BE-07 adds that status. If the row is created at upload, the total does
   not exist yet. The alternative is to create the row only after a successful
   extraction, which makes the column not null but leaves no place to record a
   failed upload.
2. **What happens to a user's statements when the user row is deleted?**
   *Recommended: `RESTRICT`.* The database refuses to delete a user that still
   has statements, so financial data is never removed as a side effect. Nothing
   deletes users today. The alternative, `CASCADE`, would erase the statements
   (and, with BE-29, their transactions) silently.
3. **Where does `name` come from, and may it be empty?** *Recommended: not
   null, not empty, taken from the uploaded file's name without the extension
   by BE-03 and BE-05.* BE-03 may let the person edit it later. The file name
   is stored as the person's own label, not as the file: BE-04 decides that the
   PDF is not kept. The name never goes into a log (BE-21).

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-30 merged and the local database current | Agent | `cd app && make db-up && make db-upgrade && make db-current` | `0003 (head)` |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation |
| `pg_dump` and `psql` on the owner's machine | Owner | `pg_dump --version && psql --version` | `pg_dump` 17 or newer |
| The owner's connection string | Owner | `stat -f '%Lp' ~/.config/odiservices/supabase.env` | `600` |
| Supabase has `0003` applied | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-current` | `0003 (head)` |

**Packages.** None. SQLAlchemy, Alembic and psycopg are already pinned.

**Actions that need the owner's explicit OK.** Applying `0004` to Supabase
(checks 9 and 10): the owner reads `make db-sql FROM=0003` and says "apply".
The agent never holds a production credential and never connects to Supabase.

**Cost.** None. A failed migration leaves nothing behind, because each one
runs in a transaction.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `numeric(14,2)` holds any card statement total (up to 999 999 999 999,99) | *Verified* by arithmetic: far above any card limit | `test_total_keeps_two_decimals` |
| 2 | The naming convention names the foreign key `fk_statements_user_id_users` and the model's `ForeignKey("users.id")` resolves inside schema `portal` | *Assumed*, from the SQLAlchemy documentation and `users` in `base.py` | Check 6 and `test_unknown_user_is_refused`; the drift test fails if the names differ |
| 3 | A descending index (`created_at DESC`) round-trips through the drift test with no false difference | *Assumed* | `test_models_match_migrations`, step 1. If it reports a difference, the index is declared ascending and the spec is amended |
| 4 | The default privileges from `0001` reach the new table, so `app_backend` needs no `GRANT` | *Verified* for `users` and `categories` (BE-27, BE-30) | `test_app_role_reads_and_writes_statements` |
| 5 | The drift test does not see `server_default` (BE-35 is not done) | *Verified* by reading `migrations/options.py` | `test_defaults_are_set_on_insert` tests the behaviour directly |
