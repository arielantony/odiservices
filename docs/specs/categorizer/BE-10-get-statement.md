# Spec — BE-10 Get one statement with its transactions

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-10 |
| **Story** | None. FE-06 and FE-08 come after it |
| **Depends on** | BE-05 (Ready, not Done: this item starts only when BE-05 is Done), BE-24 (Done), BE-28 (Done), BE-29 (Done), BE-30 (Done) |
| **Spec status** | Approved (2026-11-11), with the recommended answers to section 6 |
| **Date** | 2026-11-11 |

## 1. Goal

The board needs one statement and all its lines in one call.
`GET /api/statements/{statement_id}` returns the statement's header and its
transactions, ordered by their printed number, for the signed-in user only. It
replaces the two files the old kanban served (`/data/result.json` and
`/data/extract.json`), so the frontend no longer joins two sources. It only
reads what BE-05 writes. A statement that belongs to someone else looks exactly
like one that does not exist.

## 2. Scope

**In scope**

- `GET /api/statements/{statement_id}` and the function behind it
  (`read_statement`), with its response models.
- The 404 for missing, malformed and other users' ids (3.4).
- Tests (section 5).

**Out of scope**

- Changing a category or the reviewed flag: BE-11.
- The per-category totals: BE-12. The response has the statement's counts only.
- The category before a user move ("Movido por você"): BE-13. The response has
  no such field.
- Display labels for the categories: BE-16. The response returns `category_code`.
- Export: BE-14. Delete: BE-15. The list of statements: BE-06.
- Card name and last digits: BE-09. Processing status: BE-07. The response has
  `name` only.
- Any screen: FE-06 and later.

## 3. Design

### 3.1 The route

`GET /api/statements/{statement_id}`, behind the Access check (BE-23) and
`Depends(current_user)` (BE-24), as `/api/me` is. The statement is found by its
id and the user in the token, never by a user id in the path. The id is the only
data in the URL.

The path parameter is declared as `str` and parsed inside the handler with
`uuid.UUID(...)`. A malformed id is then a `404` with the not-found body. It must
not reach the `422` handler of BE-05 (3.5 of that spec), which would say that the
statement data is invalid.

### 3.2 The response

`200`, with `Cache-Control: no-store`:

```json
{
  "id": "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c10",
  "name": "Fatura Cartão Exemplo, set/2026",
  "total": "11906.35",
  "created_at": "2026-11-10T14:03:00Z",
  "transaction_count": 17,
  "doubtful_count": 2,
  "transactions": [
    {"id": "b2d4e9f0-3c1a-4e7b-9d62-8f0a1c5e6b71", "item_number": 1,
     "section": "purchases", "printed_date": "05/09",
     "description": "Distribuidora Exemplo Ltda", "amount": "1250.00",
     "category_code": "FORNECEDOR", "doubtful": false, "reviewed": false}
  ]
}
```

- The header fields have the names of BE-05's `201` response (`id`, `name`,
  `total`, `transaction_count`, `doubtful_count`), so the import and the read
  share one shape.
- `total` is a decimal string, or `null` when the row has none. BE-28 allows it;
  BE-05 always stores one.
- Money is a decimal string with two places, from `numeric(14,2)`: `"1250.00"`,
  `"-49.90"`. Never a float.
- Each transaction has its own `id` (the board needs it for BE-11),
  `item_number` as stored, `section` in English (`purchases`, `international`,
  `products`), `printed_date`, `description`, `amount`, `category_code`,
  `doubtful` and `reviewed`.
- `item_number` is returned as stored. Gaps stay, nothing is renumbered (BE-05
  accepts gaps).
- `transactions` is ordered by `item_number`, ascending. The unique pair
  (`statement_id`, `item_number`) of BE-29 makes the order deterministic.
- `created_at` is converted to UTC and written as ISO 8601 ending in `Z`. The
  read formats it itself, since Pydantic's default is `+00:00`. `updated_at` is
  not returned.
- A statement with no transactions is `200` with `transaction_count: 0` and
  `transactions: []`, not an error. BE-05 refuses such an import, so this is
  only reachable later (BE-15 or a repair), and the read does not change.

### 3.3 Ownership

Two queries, and the second runs only after the first finds the row:

1. `select` the statement `where id = :id and user_id = :current.id`. No row is
   a `404`.
2. `select` its transactions `where statement_id = :id order by item_number`.

The database policy of BE-28 (3.2) does not filter by user, so this filter is
code. No transaction of another user's statement is read.

### 3.4 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` |
| 503 | `database_unavailable` | from BE-24 (`DATABASE_UNAVAILABLE`, `server/db/session.py`), unchanged. Also for a database error in the route's queries |

The `404` is one response for three cases: an unknown id, a malformed id and
another user's id. Status and body are the same in all three, and so are the
headers, apart from `X-Request-Id`, which is per request.

A database error inside this route's own two queries (a `DBAPIError`) is a
`503 database_unavailable`, as BE-24 does for the user row
(`server/users.py`): the log gets one `database_error` line with the exception's
class name only, never the driver message, which can hold the host. The `503`
for a missing engine comes from the session, before the route runs.

### 3.5 Logging

The request log of BE-21 is the only log line. It records the matched route
template, `/api/statements/{statement_id}`, never the raw path, so the id is not
logged. The route writes nothing else to the log. No description, amount or name
appears in any line.

### 3.6 Steps

One step, about 220 lines with the tests. Branch `feat/be-10-get-statement`,
from `origin/main`, PR to `main`.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add `read_statement(session, user, statement_id)` and the response models. The module is created by BE-05 |
| `app/api/server/routes/statements.py` | Add `GET /api/statements/{statement_id}`. The module is created by BE-05 |
| `app/api/tests/test_statement_read.py` | New: section 5, no database |
| `app/api/tests/test_statement_read_db.py` | New: section 5, marker `db` |
| `docs/BACKLOG.md` | BE-10: status to In progress, then the PR link |

No migration, no setting, no dependency, no change to the fixture or to the
error handler.

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge* list: no migration and no deploy. There is no live
server check either. The dev bypass (BE-25) is not a dependency, so the route is
checked through the test client, with the Access verifier faked.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 1 | `cd app && make test-api` | All pass. The `db` tests are deselected (`pytest.ini`) |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_statement_read_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_read.py -v` | All pass: `test_read_requires_access`, `test_malformed_id_is_404_not_422`, `test_read_response_headers`, `test_read_logs_carry_no_description`, `test_no_engine_is_503`, `test_query_error_is_503_without_details` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_read_db.py -v` | All pass: `test_get_canonical_statement_in_order` (17 lines, `item_number` 1 to 17, `total` `"11906.35"`, `doubtful_count` 2), `test_gaps_and_money_are_kept_as_stored`, `test_other_users_statement_is_identical_to_missing`, `test_null_total_is_returned_as_null` |

## 5. Tests

Fictitious data only. The db tests import the canonical fixture through
`import_statement` (BE-05). The gap test uses a three-line payload of its own:
"Loja Exemplo" 10.00 (`item_number` 1), "Loja Exemplo" 20.00 (2), "Estorno
Exemplo" -5.50 (5), total 24.50. Two users are created through the BE-24 path
with the helpers of `tests/access_helpers.py`, as `test_users_resolution_db.py`
does, with the verifier faked. No call leaves the machine.

`test_statement_read.py` (no database). Which app each test uses is stated in
the table: the Access chain and `get_session` are real wherever the test is
about them.

| Test | App | Asserts |
|---|---|---|
| `test_read_requires_access` | Plain `create_app` with the Access verifier faked (`access_helpers.py`), no overrides | No token gives `401`, and the route's query is never reached |
| `test_malformed_id_is_404_not_422` | Overrides: `get_session` a fake session, `current_user` a `User` | `abc-123`, a uuid one character short and `%20` each give `404` with `statement_not_found`, never `invalid_statement` |
| `test_read_response_headers` | Overrides, as above | A `200` carries `Cache-Control: no-store`; amounts and total are strings (`"1250.00"`, `"-49.90"`), never numbers |
| `test_read_logs_carry_no_description` | Overrides, as above | Captured stdout (as `test_users_resolution_db.py` reads it) holds the request line with `"route": "/api/statements/{statement_id}"` and no id. A planted description `Loja Exemplo Sigilo` and amount `1234.56` appear in no line |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token | `503` with `database_unavailable` and the BE-24 message |
| `test_query_error_is_503_without_details` | Overrides, as above, with a fake session whose `execute` raises `OperationalError` carrying a host name | `503` with `database_unavailable`; the host name is in neither the body nor the log, which holds `database_error` and the class name |

`test_statement_read_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_get_canonical_statement_in_order` | `200`; `name`; `total` `"11906.35"`; 17 transactions in `item_number` order 1 to 17; `doubtful_count` 2, on "Software Gestão Teste" and "Compra Não Identificada"; `reviewed` false everywhere; codes as in the fixture; `created_at` ends in `Z` and parses as a UTC datetime |
| `test_gaps_and_money_are_kept_as_stored` | `item_number` 1, 2, 5 come back as stored; amounts `"10.00"`, `"20.00"`, `"-5.50"`; `total` `"24.50"` |
| `test_other_users_statement_is_identical_to_missing` | The second user gets `404` for the first user's id, with the same status, body bytes and headers as for a random uuid4, except `X-Request-Id`, which the request log sets on every response (`server/request_log.py`). The first user gets `200` |
| `test_null_total_is_returned_as_null` | A statement inserted through the ORM with no total gives `"total": null`, `transaction_count` 0 and `transactions` `[]` |

## 6. Open questions

Answered by the owner on 2026-11-11: all four follow the recommendation. Each
question below keeps its recommendation for the record.

1. **Counts and total in the response.** *Recommended: yes,* with BE-05's
   names (`total`, `transaction_count`, `doubtful_count`), so the board header and
   the import share one shape. The alternative is the lines only, and FE-06 counts
   them in the browser, repeating a rule the server already owns.
2. **Return `doubtful` and `reviewed` now.** *Recommended: yes.* FE-09 and FE-10
   need them from the first read. Leaving them out would make BE-11 add fields to
   the same route in a second change. The alternative is to add them with BE-11.
3. **Caching.** *Recommended: `Cache-Control: no-store`, no ETag.* BE-11 changes
   the same data from the same board, and a conditional read could show old
   categories after a move. An ETag can come with BE-11, which owns the version.
   The alternative is an ETag now, built from `updated_at`.
4. **`created_at` in the response.** *Recommended: yes,* as UTC ISO 8601. FE-06
   can show when the statement was sent. The alternative is to leave it out until
   BE-06 settles the list's date.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-05 merged: `POST /api/statements` exists | Agent | `cd app/api && grep -n 'post("/api/statements"' server/routes/statements.py` | One line |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| Categories seeded | Agent | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass, BE-24 tests included |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production
database, no deploy.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | The route takes the user as `Depends(current_user)`, as `/api/me` does | *Verified*, `server/routes/me.py` and `server/users.py` | Check 3 |
| 2 | The request log records the matched route template and never the raw path | *Verified*, `server/request_log.py` (`route.path`, "unmatched" otherwise) | `test_read_logs_carry_no_description` |
| 3 | The `503` with no engine and the `DATABASE_UNAVAILABLE` message come from `get_session` | *Verified*, `server/db/session.py` | `test_no_engine_is_503` |
| 4 | `make test-api` deselects `db` tests, and the Makefile forwards no arguments to pytest | *Verified*, `pytest.ini` (`addopts = -m "not db"`) and the `test-api` target | Checks 1 and 3 call pytest directly |
| 5 | `tests/access_helpers.py` and the BE-24 `db` test pattern exist | *Verified*, file listing of `app/api/tests/` | Check 4 imports nothing new |
| 6 | `Statement` and `Transaction` have the columns, the unique pair and the index this spec uses | *Verified*, `server/db/models.py` | Check 4 |
| 7 | BE-05's `server/statements.py`, `server/routes/statements.py`, the fixture and its `RequestValidationError` handler exist as its spec says | *Assumed*: BE-05 is approved, not merged | Prerequisites, first two rows |
| 8 | psycopg 3 returns a `numeric(14,2)` as a `Decimal` that keeps its scale (`Decimal("1250.00")`), so two places are kept | *Assumed* | `test_gaps_and_money_are_kept_as_stored`; if the scale is lost, the formatting is fixed in the read, not the column |
| 9 | Overriding `get_session` and `current_user` through `app.dependency_overrides` works with `create_app`, as the BE-24 tests do | *Assumed* from the `add_get` helper in `tests/conftest.py` | First run of `test_statement_read.py` |
