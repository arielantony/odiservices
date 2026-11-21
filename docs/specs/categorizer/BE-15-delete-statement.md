# Spec — BE-15 Delete a statement and its transactions

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-15 |
| **Story** | FE-18 (Delete a statement with confirmation, backlog row, "Needs prototype"; no `.feature` file yet). This spec is API-only, so it does not need the prototype. FE-18 still does, and its own spec will say so |
| **Prototype** | None for this item (API-only, `docs/BACKEND_GUIDELINES.md`) |
| **Depends on** | BE-10 (Done, #89 and #91) |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

A person must be able to remove a card statement they sent, with all its lines,
so that the sensitive data does not stay on the server. `DELETE
/api/statements/{statement_id}` deletes one statement of the signed-in user. The
lines go with it by the database's `ON DELETE CASCADE`, in the same transaction.
The delete is hard: no soft-delete flag, no trash. The confirmation is FE-18's
job; the server only checks ownership and performs the delete.

## 2. Scope

**In scope**

- `DELETE /api/statements/{statement_id}` and the function behind it
  (`delete_statement`), in `server/statements.py`.
- The 404 for missing, malformed, already deleted and other users' ids.
- Verification that the existing grants and RLS policies allow the delete (3.5).
  No migration is needed (section 3.5).
- Tests (section 5).

**Out of scope**

- Deleting the uploaded PDF blob (`portal.statement_uploads`, BE-04). That
  table does not exist yet. When BE-04 is written, its spec adds the check that
  its `ON DELETE CASCADE` removes the blob (section 6, question 4).
- Confirmation text and the button: FE-18 and its prototype.
- Deleting a statement that is still being extracted (BE-03, BE-07). Section
  6, question 3 says what this item does with it.
- Export before delete: BE-14.
- Any screen: FE-18.

## 3. Design

### 3.1 The route

`DELETE /api/statements/{statement_id}`, behind the Access check (BE-23,
application-wide) and `Depends(current_user)` (BE-24), as BE-10's `GET` is.
The id is declared as `str` and parsed with `uuid.UUID(...)` in the route, so a
malformed id is a `404`, not a `422`. The method is new on the same path as
BE-10's `GET`, so no route is added and no other path changes.

There is no body and no query parameter.

### 3.2 The response

- `204` with no body, and `Cache-Control: no-store`, on success.
- `404` `statement_not_found` otherwise (3.6). A second delete of the same id is
  a `404`, not a `204` (section 6, question 1).

### 3.3 The delete

One statement, filtered by the user in the token, never by a user id from the
client:

```sql
DELETE FROM portal.statements
WHERE id = :sid AND user_id = :current_user_id;
```

Through the ORM this is `delete(Statement).where(Statement.id == sid,
Statement.user_id == user.id).execution_options(synchronize_session=False)`.
The route then reads the row count:

- `1`: commit, return `204`. The `transactions` rows of the statement are removed
  by the foreign key `fk_transactions_statement_id_statements`, declared
  `ON DELETE CASCADE` in migration `0005` (checked in `server/db/models.py`, the
  `ondelete="CASCADE"` on `Transaction.statement_id`). The cascade runs in the
  same transaction, so a failure removes nothing.
- `0`: no row of this user has that id. Roll back, return `404`. Nothing else
  changes.

The one `DELETE` is the ownership check and the delete together, so there is no
window between a read and a delete, and two concurrent deletes of the same id
cannot both succeed.

The function is `delete_statement(session, user, statement_id) -> bool`, which
returns `True` when a row was deleted. It runs in the threadpool, as BE-10's
read does.

### 3.4 Ordering of the checks

1. Parse `statement_id`. Malformed: `404 statement_not_found`.
2. The `DELETE` of 3.3. Row count `0`: `404 statement_not_found`.
3. Commit (`204`). On a `DBAPIError`: roll back, `503` (3.6).

The body is never read. A `DELETE` with a body is ignored.

### 3.5 Grants and row level security (checked)

A new migration is needed only if the `app_backend` role lacks a privilege or
the RLS policy blocks the delete. Both were checked by reading the migrations:

- **Grant.** `0001_baseline.py` (lines 46 to 49) runs
  `ALTER DEFAULT PRIVILEGES IN SCHEMA portal GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend`.
  Every table created later by the migrating role gets `DELETE` for
  `app_backend`, and `statements` (`0004`) and `transactions` (`0005`) are
  such tables. *Verified* in the migrations, and checked in the database by
  check 5.
- **RLS.** `enable_backend_only_rls` (`migrations/helpers.py`, lines 17 to 20)
  creates `CREATE POLICY backend_only ... TO app_backend USING (true) WITH CHECK
  (true)`. A policy without `FOR` applies to all commands, so `DELETE` passes.
  *Verified* in the helper. The existing invariant test
  (`test_migrations_db.py`, `rls_violations`) already asserts that `app_backend`
  holds `SELECT,INSERT,UPDATE,DELETE` on every `portal` table.
- **Cascade.** A referential action runs as the owner of the referencing table
  and is not subject to RLS on that table. The `DELETE` on `statements` needs
  `SELECT` on `id` and `user_id`, which `app_backend` has.

Therefore **no migration, no new revision, and no After-merge migration step.**
The reserved revision `0010` is not used by this item. If a later check shows
that a privilege is missing, this section is wrong and the spec is updated
before code continues.

### 3.6 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` (BE-10, unchanged) |
| 503 | `database_unavailable` | from BE-24, unchanged. Also for a `DBAPIError` in the delete; the log carries the class name only |

The `404` is one answer for a malformed id, an unknown id, a statement already
deleted and another user's id. Its status, body and headers are the same in all
four cases, except `X-Request-Id`.

An `IntegrityError` is re-raised, as in BE-05, BE-11 and BE-12. No foreign key
refers to `statements` with `RESTRICT` today, so none is expected.

### 3.7 Logging

The request log of BE-21 is the only line. It records the route template,
`/api/statements/{statement_id}` with the method `DELETE`, never the raw path. The
route writes one `database_error` line on a `DBAPIError`, with the class name
only. No id, count, name or amount appears in any line. The request log writes
the status, so a `204` or a `404` is visible without a new line.

### 3.8 Steps

One step, about 250 to 350 lines with the tests. Branch
`feat/be-15-delete-statement`, from `origin/main`, PR to `main`.

### 3.9 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add `delete_statement(session, user, statement_id) -> bool` (3.3) |
| `app/api/server/routes/statements.py` | Add `@router.delete("/api/statements/{statement_id}")` returning `Response(status_code=204, headers={"Cache-Control": "no-store"})` |
| `app/api/tests/test_statement_delete.py` | New: section 5, no database |
| `app/api/tests/test_statement_delete_db.py` | New: section 5, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-15 to In progress, then the PR link. Not changed by this spec |

No migration, no setting, no dependency, no change to `server/main.py`, and no
change to `test_access_routes.py`: its every-route test already sends `DELETE`
to every path with a sample id and expects `401` or `405` (lines 93 to 100).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge (deploy)* list for the code: no migration and no
deploy. One read-only check for the owner is listed at the end of this section.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-10 is merged | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_statement_delete_db.py` and the existing grant and RLS invariant tests of `test_migrations_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_delete.py -v` | All pass: `test_delete_requires_access`, `test_malformed_id_is_404`, `test_delete_response_headers`, `test_delete_logs_carry_no_values`, `test_missing_statement_is_404`, `test_no_engine_is_503`, `test_query_error_is_503_without_details` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_delete_db.py -v` | All pass: `test_delete_removes_statement_and_its_transactions`, `test_other_users_statement_is_404_and_kept`, `test_second_delete_is_404`, `test_delete_leaves_other_statements_alone` |
| 5 | The grants on the local database, as the owner: `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select has_table_privilege('app_backend','portal.statements','DELETE'), has_table_privilege('app_backend','portal.transactions','DELETE');"` | `t|t` |
| 6 | The cascade is declared: `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select confdeltype from pg_constraint where conname = 'fk_transactions_statement_id_statements';"` | `c` (`c` is CASCADE in `pg_constraint.confdeltype`) |

**After merge (read-only, owner).** Not a deploy and not a migration: the owner
confirms that the production database has the grants of 3.5, from `main`, with
the owner's own connection. The agent does not run it.

```
psql "$PRODUCTION_OWNER_URL" -Atc "select has_table_privilege('app_backend','portal.statements','DELETE'), has_table_privilege('app_backend','portal.transactions','DELETE');"
```

Expected `t|t`. If it prints `f`, the migration `0001` was not applied as
written, and the item stays *In progress* until the owner decides the fix. The
item is Done when the merge checks pass and this line is recorded in the Done PR.

## 5. Tests

Fictitious data only. The db tests import the canonical fixture through
`import_statement` (BE-05), and use a second user for the ownership cases. Users
are created through the BE-24 path with `tests/access_helpers.py`, as
`test_statement_read_db.py` does, with the verifier faked. No call leaves the
machine.

`test_statement_delete.py` (no database). Which app each test uses is stated in
the table: the Access chain and `get_session` are real wherever the test is
about them.

| Test | App | Asserts |
|---|---|---|
| `test_delete_requires_access` | Plain `create_app` with the Access verifier faked, no overrides | No token gives `401`, and `delete_statement` is never reached |
| `test_malformed_id_is_404` | Overrides: `get_session` a fake session, `current_user` a `User` | `abc-123`, a uuid one character short and `%20` each give `404` with `statement_not_found`, and the fake session records no delete |
| `test_delete_response_headers` | Overrides, as above, the fake's `DELETE` reporting one row | `204`, empty body, `Cache-Control: no-store` |
| `test_delete_logs_carry_no_values` | Overrides, as above | The request line holds `"route": "/api/statements/{statement_id}"` and no id. A planted name `Fatura Sigilo` and amount `1234.56` appear in no line |
| `test_missing_statement_is_404` | Overrides, the fake's `DELETE` reporting zero rows | `404` with `statement_not_found`, and the fake records a rollback and no commit |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token | `503` with `database_unavailable` and the BE-24 message |
| `test_query_error_is_503_without_details` | Overrides, a fake session whose `execute` raises `OperationalError` with a host name | `503` with `database_unavailable`; the host name is in neither the body nor the log |

`test_statement_delete_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_delete_removes_statement_and_its_transactions` | The fixture is imported for user A: 17 lines. `DELETE` gives `204`. Read as the owner (not as `app_backend`), `portal.statements` has no row with that id and `portal.transactions` has no row with that `statement_id`. Then a `GET` of the same id is `404` |
| `test_other_users_statement_is_404_and_kept` | The fixture is imported for user A. User B's `DELETE` gives `404`, with the same status, body bytes and headers as for a random uuid4 (except `X-Request-Id`). Read as the owner, the statement and its 17 lines still exist. User A's `GET` is still `200` |
| `test_second_delete_is_404` | `DELETE` gives `204`, the second `DELETE` of the same id gives `404` with the body of an unknown id. No row is touched by the second call |
| `test_delete_leaves_other_statements_alone` | User A has two statements (the fixture and the three-line gap payload of BE-10's tests, "Fatura Lacunas Exemplo"). Deleting the first leaves the second with its three lines and its total `"24.50"` |

## 6. Open questions

Each question has a recommendation. The owner is away: each recommendation is
adopted, as delegated.

1. **Second delete of the same id: `404` or `204`.** *Recommended: `404`
   `statement_not_found`, not idempotent (delegated: the owner is away; the
   recommendation will be adopted).* The statement is gone, so the answer for
   that id is the same as for any unknown id, and nothing reveals whether it
   once existed. A `204` would also hide a double click from the board, which
   can then refresh its list on `404` and show that the statement is gone. The
   alternative is `204` on any repeat, which makes the call idempotent but
   answers "deleted" for an id the person never owned.

2. **Hard delete or soft delete.** *Recommended: hard delete, with the lines
   removed by `ON DELETE CASCADE` in the same transaction (delegated: the owner
   is away; the recommendation will be adopted).* The data is a card statement,
   and the privacy rules of `CLAUDE.md` say the real data must not stay around.
   A soft delete keeps the lines and the blob (BE-04) in the database after the
   person asked for them to go, and needs its own retention rule. The alternative
   is a `deleted_at` column, which would also need every read of BE-06, BE-10,
   BE-11 and BE-12 to filter it. The item is cheaper and safer as a hard delete.

3. **Deleting a statement that is still `processing` or `failed`.** *Recommended:
   allowed, for any status (delegated: the owner is away; the recommendation
   will be adopted).* A person must be able to remove a failed upload, and the
   status (BE-07) is not known to this item yet. BE-03's background extraction
   may then try to write to a deleted statement. It updates zero rows, and BE-03
   must treat that as "the statement is gone" and stop, not as an error to
   report to the person. The BE-03 spec must say so when it is written. The
   alternative is to refuse with `409` while `processing`, which would make the
   person wait for an extraction they want to cancel.

4. **The uploaded PDF blob (BE-04).** *Recommended: the blob is removed by
   `ON DELETE CASCADE` from `portal.statement_uploads(statement_id)`, which BE-04
   declares, and BE-04's spec carries the check (delegated: the owner is away;
   the recommendation will be adopted).* This item does not depend on BE-04,
   and the table does not exist. The check is BE-04's, not this one's, so
   nothing in this item's verification needs BE-04.

5. **Confirmation on the server.** *Recommended: no confirmation field in the
   request (delegated: the owner is away; the recommendation will be adopted).*
   The confirmation is the UI's (FE-18). A required body such as
   `{"confirm": true}` would be a second safety net against a bad client, but
   every client is the portal's own, and a body on a `DELETE` is awkward for
   proxies. The alternative is a required body, which needs its own `422` rule.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| The categories are seeded (10) | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| The `app_backend` grants exist locally | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select has_table_privilege('app_backend','portal.statements','DELETE');"` | `t` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| The owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted (delegated) |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No migration,
no production database, no deploy. The read-only production check of section 4
is run by the owner.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `0001_baseline.py` sets `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend`, so `statements` and `transactions` have `DELETE` | *Verified*, `app/api/migrations/versions/0001_baseline.py`, lines 46 to 49 | Check 5 |
| 2 | `enable_backend_only_rls` creates a policy with no `FOR` clause, so it covers `DELETE` | *Verified*, `app/api/migrations/helpers.py`, lines 17 to 20 | Check 2 (the db test deletes as `app_backend`) |
| 3 | `transactions.statement_id` is `ON DELETE CASCADE`, in migration and ORM | *Verified*, `0005_transactions.py` line 75 and `server/db/models.py` line 132 | Check 6, and `test_delete_removes_statement_and_its_transactions` |
| 4 | `Statement` declares no ORM `relationship` with a cascade, so the ORM does not try to delete the lines itself | *Verified* by reading `server/db/models.py`: no `relationship(` on `Statement` | `test_delete_removes_statement_and_its_transactions` |
| 5 | A referential action on `transactions` runs without `DELETE` on `transactions` for `app_backend`, and is not filtered by RLS | *Assumed* (PostgreSQL's RI triggers run as the referencing table's owner). The grant exists anyway, so the check does not depend on it | `test_delete_removes_statement_and_its_transactions` |
| 6 | psycopg 3 and SQLAlchemy 2.0 report the affected row count of an ORM `delete(...)` with `synchronize_session=False` as `Result.rowcount` | *Assumed* | `test_missing_statement_is_404` (fake) and `test_second_delete_is_404` (real) |
| 7 | The request log writes the route template with the method, so a `204` and a `404` are visible without a new line | *Verified*, `server/request_log.py` (route template; the BE-21 line carries status) | `test_delete_logs_carry_no_values` |
| 8 | `test_access_routes.py` sends `DELETE` to every path with a sample id and expects `401` or `405` | *Verified*, lines 93 to 100 | Check 1 |
| 9 | `portal.statement_uploads` does not exist yet, so no blob is removed by this item | *Verified*, the migration listing (`0001` to `0005` only) | Check 1 |

## Amendments before approval (2026-11-21)

- BE-04's blob table cascades on delete (BE-04 check). A statement in `processing` can be deleted; BE-03's job must tolerate a vanished row (its spec 3.6: a missing row ends the job without error).
