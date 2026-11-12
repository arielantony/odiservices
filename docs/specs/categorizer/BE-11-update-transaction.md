# Spec — BE-11 Update a transaction's category and reviewed flag

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-11 |
| **Story** | None. FE-09 (move by drag), FE-10 (confirm a doubt) and FE-12 (undo) use it. FE-15 and FE-16 have no `.feature` yet (*Needs prototype*) |
| **Depends on** | BE-10 (Done once #91 is merged: this item starts only then). BE-05, BE-29 and BE-30 (Done) |
| **Spec status** | Approved (2026-11-11), with the recommended answers to section 6 |
| **Date** | 2026-11-11 |

## 1. Goal

The board changes the category of one line and confirms its doubt. Both are
saved with one call, `PATCH /api/statements/{statement_id}/transactions/{transaction_id}`,
which sets the transaction's `category_code` and/or `reviewed`, for the signed-in
user only, and returns the stored line. Undo (FE-12) is the same call with the
previous values, so the server keeps no history.

## 2. Scope

**In scope**

- `PATCH /api/statements/{statement_id}/transactions/{transaction_id}` and the
  function behind it (`update_transaction`), with its request model.
- The 404s for a missing, malformed or other user's statement, and for a
  transaction that is not in that statement (3.4).
- The pending-review count in the statement read (3.6), which is a change to
  BE-10 and needs the owner's approval (section 6, question 2).
- Tests (section 5).

**Out of scope**

- Original category and "Movido por você": BE-13. The response has no such field.
  FE-09 and FE-12 scenarios that show "Movido por você" therefore also need BE-13.
  The backlog lists only BE-11 for them: a gap for the owner, not a blocker here.
- Changing `doubtful`. The extraction sets it (BE-05); no route changes it.
- Bulk changes: FE-16 (multi-select) and FE-17 (undo all) send one PATCH per
  transaction. A batch route is a later item if the board needs it.
- Totals and distribution: BE-12. Export: BE-14. Delete: BE-15.
- Any screen: FE-09 and later.

## 3. Design

### 3.1 The route

`PATCH /api/statements/{statement_id}/transactions/{transaction_id}`, behind the
Access check (BE-23) and `Depends(current_user)` (BE-24), as BE-05 and BE-10 are.
The statement is found by its id and the user in the token, never by a user id.
Both ids are declared as `str` and parsed in the handler with `uuid.UUID(...)`,
so a malformed id is a `404`, never a `422`.

The check order is fixed, and each step is the reason the next one is safe:

1. Parse `statement_id`. Malformed: `404 statement_not_found`.
2. Select the statement `where id = :sid and user_id = :current.id`. No row:
   `404 statement_not_found`. This runs before the body is read, so a foreign id
   and a missing one get the same answer for any body.
3. Check the body size (3.2). Over the limit: `413 payload_too_large`.
4. Parse and validate the body (3.2). Failure: `422 invalid_statement`.
5. Parse `transaction_id`. Malformed: `404 transaction_not_found`.
6. Select the transaction `where id = :tid and statement_id = :sid` (the
   statement is already owned), with `FOR UPDATE`. No row:
   `404 transaction_not_found`. A transaction of another of the user's
   statements is also not found.
7. If `category_code` is sent, check it is in `portal.categories` (read from the
   table, as BE-05 does). Unknown: `422 unknown_category`.
8. Compare the requested values with the row. If none differs, nothing is
   written (3.5). Otherwise write them and commit.
9. Return the row (3.2).

### 3.2 The request and the response

Request body, JSON, at most 1 KiB (`Content-Length`, and the bytes read are
checked too, as BE-05 does):

```json
{"category_code": "OPERACIONAL", "reviewed": true}
```

- At least one of the two fields is required. `{}` is refused.
- `category_code`: a string, not null. Its value is checked in step 7.
- `reviewed`: a JSON boolean, not null. A string such as `"true"` is refused.
- Any other field is refused, including `doubtful`, `id`, `statement_id` and
  `item_number`. The model is `extra="forbid"` and `strict=True`.
- A body that is not JSON is `422 invalid_statement`. The route raises
  `RequestValidationError` (BE-05, 3.5), and the handler in `server/main.py`
  answers the portal's format.

Response `200`, with `Cache-Control: no-store`. It is one transaction, with the
same fields and names as an element of BE-10's `transactions[]`:

```json
{"id": "d7a1f3c2-5e8b-4a6d-9c10-3b2e7f9a4d55", "item_number": 2,
 "section": "purchases", "printed_date": "06/09",
 "description": "Loja Exemplo", "amount": "20.00",
 "category_code": "OPERACIONAL", "doubtful": true, "reviewed": true}
```

- `amount` is a decimal string with two places, as in BE-10.
- `updated_at` is not returned, as in BE-10.
- The response does not carry the statement's counts. After a change the board
  reads `GET /api/statements/{statement_id}` again to refresh its counts.

### 3.3 Concurrency (answers BE-10, question 3)

**Recommended now: last write wins, with set-to-value semantics. No version and
no `If-Match`.** Each request names the value it wants, never a change ("set to
OPERACIONAL", not "move"), so a retried request gives the same result, and undo
sends the previous values. The `FOR UPDATE` in step 6 serializes two requests on
the same line, so each one sees a committed row.

The cost is that two open browsers of the same user can overwrite each other
silently. The statements belong to one person, and FE-12 undo after a reload is
not in the stories. The alternative is the version that BACKEND_GUIDELINES
already allows: `If-Match` carries the transaction's `updated_at`, and a stale
value gets `409 transaction_changed` with the current row and `version` in the
body, so the client can reload. It is not built now because it changes the
response of every write and the board's undo logic, and `updated_at` already
exists, so it can be added later without a migration.

### 3.4 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` (BE-10, unchanged) |
| 404 | `transaction_not_found` | `A transação não foi encontrada.` (new) |
| 413 | `payload_too_large` | `A fatura enviada é grande demais.` (BE-05, reused) |
| 422 | `invalid_statement` | `Os dados da fatura são inválidos.` (BE-05, reused) |
| 422 | `unknown_category` | `A fatura tem uma categoria desconhecida.` (BE-05, reused) |
| 503 | `database_unavailable` | from BE-24, unchanged. Also for a `DBAPIError` in this route's queries; the log carries the class name only |

The `404 statement_not_found` is one response for three cases (an unknown id, a
malformed id, another user's id), with the same body and headers apart from
`X-Request-Id`, as in BE-10.

`transaction_not_found` is separate, because it is reached only after the
statement is confirmed as the user's: it reveals nothing about other users.

No error body carries a description, an amount or the category text the caller
sent.

An `IntegrityError` on `fk_transactions_category_code_categories` during the
write (a category removed between steps 7 and 8, which the owner's SQL can do)
is mapped to `422 unknown_category`. Any other `IntegrityError` is raised, as
BE-05 does.

### 3.5 Writing

- If the requested values equal the stored ones, the route does not execute an
  `UPDATE`. It returns the row with `200`, and `updated_at` stays as it was. This
  is the "dropping a card back on its own lane changes nothing" case of FE-09.
- Otherwise it sets the changed fields and commits. `updated_at` is set by the
  column's `onupdate` (`server/db/models.py`, as for every table).
- The statement's own `updated_at` is not changed by a line edit.
- `doubtful` is never written.

### 3.6 Pending review (a change to BE-10)

FE-10 needs the count "Para revisar" to drop after a confirmation, and FE-15
needs "Revisar N dúvidas". BE-10 returns `doubtful_count`, the number of lines the
extraction marked as doubts, which does not change when a doubt is confirmed.
That is the wrong number for the board.

The rule, which BE-11 owns:

- **pending review** = `doubtful` and not `reviewed`;
- confirming a doubt sets `reviewed` to `true`;
- undoing the confirmation sets it back to `false`, and the doubt is pending again
  (FE-12);
- a move sends `reviewed: true` with the new category, because the person has
  acted on the line (see section 6, question 3).

**Change to BE-10 (needs the owner's approval, see section 6, question 2):** the
statement read gets one more header field, `pending_review_count`, the number of
lines with `doubtful` true and `reviewed` false. `doubtful_count` stays as it is.
The transaction object of BE-10 does not change. BE-10's Section 3.2 and its
verification row for the counts are updated in the same PR, and BE-10's test
`test_get_canonical_statement_in_order` asserts `pending_review_count` `2` on the
fixture (`reviewed` false on both doubts).

### 3.7 Logging

The request log of BE-21 is the only log line. It records the route template,
`/api/statements/{statement_id}/transactions/{transaction_id}`, never the raw
path, so no id is logged. The route writes nothing else to the log. No body, no
description, no category text and no amount appears in any line.

### 3.8 Steps

One step, about 350 lines with the tests. Branch `feat/be-11-update-transaction`,
from `origin/main` after BE-10 is merged, PR to `main`. If the code passes 500
lines, I stop and propose a split at the seam between the route (3.1, 3.2, 3.4)
and the writing (3.5, 3.6).

### 3.9 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add the request model (`extra="forbid"`, `strict=True`), `update_transaction(session, user, statement_id, transaction_id, patch)`, and the pending count in the read (3.6). The transaction serializer is shared with BE-10's read |
| `app/api/server/routes/statements.py` | Add `PATCH /api/statements/{statement_id}/transactions/{transaction_id}` |
| `app/api/tests/test_transaction_update.py` | New: section 5, no database |
| `app/api/tests/test_transaction_update_db.py` | New: section 5, marker `db` |
| `app/api/tests/test_statement_read_db.py` | BE-10's db test: assert `pending_review_count` (3.6) |
| `docs/specs/categorizer/BE-10-get-statement.md` | Section 3.2 and the counts check, as in 3.6, after the owner approves it |
| `docs/BACKLOG.md` | At implementation: BE-11 to In progress, then the PR link. Not changed by this spec |

No migration (the grants and the RLS policy already cover `UPDATE`, section 8),
no setting, no dependency, no change to `server/main.py`: the
`RequestValidationError` handler already exists.

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge* list: no migration and no deploy. The route is checked
through the test client, with the Access verifier faked.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-10 is merged | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_transaction_update_db.py` and BE-10's db test with `pending_review_count` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_transaction_update.py -v` | All pass: `test_update_requires_access`, `test_malformed_ids_are_404`, `test_body_shape_is_422`, `test_oversized_body_is_413`, `test_update_response_headers`, `test_update_logs_carry_no_values`, `test_error_bodies_carry_no_payload_value` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_transaction_update_db.py -v` | All pass: `test_confirm_sets_reviewed_and_keeps_doubt`, `test_undo_confirm_makes_it_pending_again`, `test_move_then_undo_restores_both_fields`, `test_unknown_category_stores_nothing`, `test_other_users_statement_is_identical_to_missing`, `test_transaction_of_another_statement_is_404`, `test_same_values_do_not_touch_updated_at`, `test_change_moves_updated_at` |
| 5 | Pending review on the fixture: `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_read_db.py -k canonical -v` | Passes, with `pending_review_count` `2` and `doubtful_count` `2` |

Checks 1 to 5 run on the local database only. There is no production check: the
migration is not needed (section 8, claim 2).

## 5. Tests

Fictitious data only: the canonical fixture, imported through `import_statement`
(BE-05), and a changed copy in memory for the failure cases. Access and the user
row use `tests/access_helpers.py` and the BE-24 pattern, with the verifier faked.
No call leaves the machine.

`test_transaction_update.py` (no database, app with a fake session):

| Test | Asserts |
|---|---|
| `test_update_requires_access` | No token gives `401`, and the route's queries are never reached |
| `test_malformed_ids_are_404` | A malformed statement id gives `404 statement_not_found`; a valid statement id with a malformed transaction id gives `404 transaction_not_found`. Never `422` |
| `test_body_shape_is_422` | `{}`, `{"doubtful": false}`, `{"reviewed": "true"}`, `{"category_code": null}`, `{"reviewed": true, "id": 2}` and invalid JSON each give `422 invalid_statement` |
| `test_oversized_body_is_413` | A body over 1 KiB gives `413 payload_too_large` |
| `test_update_response_headers` | A `200` carries `Cache-Control: no-store` |
| `test_update_logs_carry_no_values` | The request line holds `"route": "/api/statements/{statement_id}/transactions/{transaction_id}"` and no id. A planted description `Loja Exemplo Sigilo` and category text `CATEGORIA SIGILO` appear in no line |
| `test_error_bodies_carry_no_payload_value` | A bad category text (`CATEGORIA SIGILO`) does not appear in the `422` body |

`test_transaction_update_db.py` (marker `db`, local Postgres, as `app_backend`):

| Test | Asserts |
|---|---|
| `test_confirm_sets_reviewed_and_keeps_doubt` | `{"reviewed": true}` on "Software Gestão Teste" gives `200`, `reviewed` true, `doubtful` still true, category unchanged |
| `test_undo_confirm_makes_it_pending_again` | `{"reviewed": false}` after that: `doubtful` true, `reviewed` false; the read counts it in `pending_review_count` again |
| `test_move_then_undo_restores_both_fields` | `{"category_code": "OPERACIONAL", "reviewed": true}` on a non-doubtful line, then the prior values back: the row equals its import state |
| `test_unknown_category_stores_nothing` | `{"category_code": "NAO EXISTE"}` gives `422 unknown_category`; the row is unchanged |
| `test_other_users_statement_is_identical_to_missing` | The second user gets `404` for the first user's statement id, with the same status, body bytes and headers as for a random uuid4 (apart from `X-Request-Id`). The same holds with an invalid body. The first user gets `200` |
| `test_transaction_of_another_statement_is_404` | Same user, a transaction id of their other statement: `404 transaction_not_found` |
| `test_same_values_do_not_touch_updated_at` | Two requests with the same body: `updated_at` equal before and after |
| `test_change_moves_updated_at` | A real change in a later request: `updated_at` is greater |

## 6. Open questions

Answered by the owner on 2026-11-11: all six follow the recommendation. Question 2
changes BE-10 (already merged): `pending_review_count` is added by this item.

1. **Concurrency.** *Recommended: last write wins with set-to-value semantics, no
   version now* (3.3). This answers BE-10, question 3. The alternative is
   `If-Match` on `updated_at`, with `409 transaction_changed` and `version` in the
   body, as BACKEND_GUIDELINES describes. It is built when the board needs it (two
   open tabs of one user), without a migration.

2. **Pending review and the change to BE-10.** *Recommended: `pending_review_count`
   (doubtful and not reviewed) added to BE-10's header, with `doubtful_count`
   unchanged, and `doubtful` never written by the API.* FE-10 says the doubt is
   "cleared" in the UI, and the count must drop. Clearing `doubtful` itself would
   need `doubtful` writable in the body, and would lose the fact that the
   extraction was unsure. The alternative is that the board counts pending lines
   in the browser from `transactions[]`. That repeats a rule the server owns, which
   BE-10 already rejected for totals. This is a change to an approved spec
   (BE-10), so it needs the owner's approval before this item is implemented.

3. **Does a move set `reviewed`?** *Recommended: the client sends `reviewed: true`
   with a category change, so the server stores what it is told and never infers
   the flag.* A moved line is one the person has acted on. The alternative is the
   server setting `reviewed` on every category change. That is one less field in
   the client's requests, but it hides a rule in the write path.

4. **`updated_at` on the statement.** *Recommended: not changed by a line edit*,
   so the statement's `updated_at` keeps meaning "the import changed". The
   alternative is to bump it, so BE-06's list can show "last changed". Not needed
   by any story now.

5. **Counts in the response.** *Recommended: the PATCH returns the transaction
   only.* The board reads the statement again to refresh its counts (3.2). The
   alternative is to return `pending_review_count` as well, which saves one request
   and couples the two routes.

6. **Malformed transaction id.** *Recommended: `404 transaction_not_found`, a code
   of its own, reached only after the statement is confirmed as the user's.* The
   alternative is one `404` for both, which reads as a missing statement and makes
   the message less useful for the board. Either is safe, because the statement
   check comes first.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| BE-05 code on `main` (`import_statement`, the handler) | Agent | `cd app/api && grep -n 'def import_statement' server/statements.py` | One line |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| Categories seeded | Agent | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6, and approval of the BE-10 change (question 2) | Owner | (none) | Recorded in this spec before implementation |

**Packages.** None.

**Actions that need the owner's explicit OK.** The BE-10 change (question 2).
None beyond the PR. No production database, no deploy.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | The route takes the user as `Depends(current_user)`, as `/api/me` and BE-05 do | *Verified*, `server/users.py` | Check 3 |
| 2 | `app_backend` may `UPDATE` `portal.transactions`, so no migration is needed | *Verified* from source: `migrations/versions/0001_baseline.py` grants `SELECT, INSERT, UPDATE, DELETE` on tables in `portal` by default privilege; `migrations/helpers.py` creates the policy `backend_only` `TO app_backend USING (true) WITH CHECK (true)` (`FOR ALL`), and `0005_transactions.py` calls it | Check 4 runs an `UPDATE` through the app's role |
| 3 | The BE-10 read exists and its transaction shape is the one in 3.2 | *Assumed*: BE-10 is approved, not merged | Preflight, first row of section 7 |
| 4 | `updated_at` changes on any `UPDATE` through the Core or ORM path, through the column's `onupdate=func.now()` | *Assumed* | `test_change_moves_updated_at`, `test_same_values_do_not_touch_updated_at` |
| 5 | `SELECT ... FOR UPDATE` through SQLAlchemy and psycopg 3 locks the row for the transaction | *Assumed* | Check 4 (the test runs in one session); the lock itself is not tested |
| 6 | A pydantic model with `strict=True` refuses `"true"` for a `bool` and `null` for a `str` field | *Assumed* | `test_body_shape_is_422` |
| 7 | An `IntegrityError` on the category foreign key is named `fk_transactions_category_code_categories` by Postgres | *Assumed* from the migration's constraint name | Not tested; the mapping of 3.4 falls back to a plain raise |
