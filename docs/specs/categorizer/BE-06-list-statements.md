# Spec — BE-06 List the current user's statements, newest first, paginated

| | |
|---|---|
| **Backlog** | Feature: Statement upload and processing › Backend › BE-06 |
| **Story** | FE-04 (`docs/stories/categorizer-home/FE-04-statement-list.feature`, still `@draft`), including the scenario "Loading older statements" |
| **Prototype** | `docs/prototypes/portal/v3.html#home` |
| **Depends on** | BE-24 (Done, `current_user`), BE-28 (Done, `portal.statements`), BE-29 (Done, `portal.transactions`; added here, see section 6, gap 1) |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

The categorizer home lists the statements the person sent, newest first, with
the name, the date sent, the total, and the count of lines still waiting for a
review. Long lists come in pages: `GET /api/statements?limit=&cursor=` returns
one page and an opaque `next_cursor` for the next one, so FE-04's "Mostrar
faturas anteriores" can add older statements to the end of the list. The read
is for the signed-in user only, and the page costs one SQL statement however
many statements it holds.

## 2. Scope

**In scope**

- `GET /api/statements` (the collection route; BE-10 owns `GET /api/statements/{id}`).
- The keyset query, the cursor codec, the limit rule and the response models
  in `server/statements.py`.
- `pending_review_count` computed by the same aggregate query as the page.
- Tests (section 5).

**Out of scope**

- The status, the failure reason, and the processing state of a statement:
  BE-07. The item fields below are the ones BE-06 owns; BE-07 adds `status`
  and `failure_code` additively.
- The card name and the last digits: BE-09 adds `card_name` and `card_last4`
  additively. They are not in this item's fields.
- Creating, deleting, exporting a statement: BE-03/05, BE-15, BE-14.
- Sorting or filtering by anything other than the newest-first order. FE-04
  has none.
- Any screen: FE-04. The note "Mais recentes primeiro" and the button
  "Mostrar faturas anteriores" are the frontend's.

## 3. Design

### 3.1 The route

`GET /api/statements`, behind the Access check (BE-23, application-wide) and
`Depends(current_user)` (BE-24), as BE-10 is. The owner is the user in the
token (`users.id`), never a user id from the client. There is no path
parameter, so the malformed-id case does not exist here.

Query parameters `limit` and `cursor` are read by hand from `request.query_params`,
not declared as FastAPI `Query(...)` parameters. Reason: `server/main.py`
(`invalid_body`, line 29) answers every `RequestValidationError` with
`422 invalid_statement`, which says the statement data is invalid. A bad
`limit` must say `invalid_limit` instead, so the route refuses it itself.

### 3.2 The response

`200`, with `Cache-Control: no-store`:

```json
{
  "items": [
    {"id": "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c10",
     "name": "Fatura Cartão Exemplo, set/2026",
     "total": "11906.35",
     "created_at": "2026-11-10T14:03:00Z",
     "transaction_count": 17,
     "pending_review_count": 2},
    {"id": "0d9a7c44-5e21-4b7f-b3a0-61c8e2f9d105",
     "name": "Fatura Cartão Demo, jul/2026",
     "total": null,
     "created_at": "2026-08-04T18:05:00Z",
     "transaction_count": 0,
     "pending_review_count": 0}
  ],
  "next_cursor": "<opaque cursor, see 3.3>"
}
```

- `items` is ordered by `created_at` descending, then `id` descending. The
  second key only breaks ties; it is the cursor's second key (3.3).
- `id` is a string UUID. `name` is the statement's name, as stored.
- `total` is a decimal string with two places, from `numeric(14,2)`, or `null`
  when the statement has none (BE-28 allows it; a statement still being
  classified has none). Never a float.
- `created_at` is UTC, ISO 8601, ending in `Z`, in seconds, as BE-10 writes it
  (`utc_text`). The frontend formats it for the screen.
- `transaction_count` is the number of lines of the statement. `pending_review_count`
  is the number of those with `doubtful` true and `reviewed` false: the rule of
  BE-11 (its spec 3.6) and of BE-10's header. Both are `0` for a statement with
  no lines.
- `next_cursor` is `null` when there is no older statement. Otherwise it is the
  cursor of the last item of this page. FE-04 shows "Mostrar faturas anteriores"
  when it is not `null`.
- An empty list is `200` with `"items": []` and `"next_cursor": null`. It is not an error.
- The response names no description, no line and no amount other than `total`.

### 3.3 Pagination

**Keyset, not offset.** A new statement at the top does not shift the pages
the person already has, and the page never scans the rows before it. The key
is `(created_at, id)`, descending.

**Limit.** The query parameter `limit` is an integer from 1 to 100. Absent, it
is 20. The rule is applied to the raw string: it must match `^[0-9]{1,3}$` and
be between 1 and 100. Anything else is `422 invalid_limit` (3.6), including
`0`, `101`, `-1`, `1.5`, `abc` and an empty value. A repeated `limit` is also
`422 invalid_limit`. The value is never clamped silently.

**Cursor.** The cursor is opaque to the client. Its value is the URL-safe
base64 of UTF-8 JSON, without padding:

```json
{"v": 1, "t": "2026-08-04T18:05:00.123456+00:00", "i": "0d9a7c44-5e21-4b7f-b3a0-61c8e2f9d105"}
```

- `t` is the `created_at` of the last item **with its microseconds**. The
  display (`created_at`, seconds) is not enough to resume the order, so the
  cursor carries the full value from the database.
- `i` is that item's `id`, in canonical form.
- `v` is the format version. Only `1` is accepted.
- The cursor is not signed (section 6, question 2). A changed cursor selects a
  different position in the **same user's** rows. It cannot show another
  person's row, because every query filters by `user_id` (3.4).
- The client sends the cursor back unchanged as `cursor=`. An absent `cursor`
  is the first page. An empty `cursor=` is `422 invalid_cursor`. A repeated
  `cursor` is `422 invalid_cursor`. A cursor longer than 512 characters is
  `422 invalid_cursor` before it is decoded.

**Decoding.** `parse_cursor` accepts a value only when every step holds: the
base64 decodes, the bytes are UTF-8, the JSON is an object with exactly the keys
`v`, `t` and `i`, `v` is `1`, `t` is an ISO 8601 timestamp **with a UTC offset**
(a naive timestamp is refused), and `i` is a UUID. Any failure is
`422 invalid_cursor`. Nothing from the cursor is logged or echoed in the answer.

### 3.4 The query

One statement reads the page and its counts. The page is limited **before** the
join, so the aggregate runs over the page's lines only, not over all the lines
of the user:

```sql
SELECT s.id, s.name, s.total_lanc_atuais, s.created_at,
       COUNT(t.id)                                              AS transaction_count,
       COUNT(t.id) FILTER (WHERE t.doubtful AND NOT t.reviewed) AS pending_review_count
FROM (
    SELECT id, name, total_lanc_atuais, created_at
    FROM portal.statements
    WHERE user_id = :current_user
      AND (created_at < :t OR (created_at = :t AND id < :i))   -- only with a cursor
    ORDER BY created_at DESC, id DESC
    LIMIT :limit_plus_one
) s
LEFT JOIN portal.transactions t ON t.statement_id = s.id
GROUP BY s.id, s.name, s.total_lanc_atuais, s.created_at
ORDER BY s.created_at DESC, s.id DESC;
```

- `:limit_plus_one` is `limit + 1`. An extra row is the proof that an older
  statement exists: the route then drops it and sets `next_cursor` from the
  last kept item. So a page that is exactly full has `next_cursor` `null`.
- The `LEFT JOIN` with `COUNT(t.id)` gives a statement with no lines a row with
  `0` and `0`. `COUNT(t.id)` and not `COUNT(*)`, for the reason of BE-12 (3.3).
- The ORM may write this differently, but the work is one statement, with no
  Python loop that runs a query per statement. Pending counts are never read
  in a second query.
- The `user_id` filter is code. The policy of BE-28 (3.2) does not filter by user.

`read_statement_page(session, user, limit, after)` returns the view. It never
returns `None`: an empty page is a valid answer, not a 404. The one query runs
in the threadpool, as BE-10's reads do. The cursor check does not query.

### 3.5 Ordering of the checks

1. `limit` (3.3): `422 invalid_limit`.
2. `cursor` (3.3): `422 invalid_cursor`.
3. The page query (3.4).

The order means a bad `limit` never reaches the database. A bad cursor never
reaches it either.

### 3.6 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors). Refusals are tuples
in `server/statements.py`, as the others are.

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 422 | `invalid_limit` | `O tamanho da página deve ser um número entre 1 e 100.` |
| 422 | `invalid_cursor` | `O cursor da página não é válido.` |
| 503 | `database_unavailable` | from BE-24 (`DATABASE_UNAVAILABLE`), unchanged. Also for a `DBAPIError` from the page query; the log carries the class name only |

There is no `404`: the collection has no id. A person with no statements gets
`200` with an empty list.

### 3.7 Logging

The request log of BE-21 is the only line. It records the route template,
`/api/statements`, not the raw path, and not the query string (the logging rule
of `docs/BACKEND_GUIDELINES.md`). The route writes one `database_error` line on
a `DBAPIError`, with the class name only. No name, total, count, cursor, limit
or id appears in any line.

### 3.8 Steps

Estimated at 400 to 450 lines with the tests. The history of this repo runs
high (BE-10 went from 220 to 480, BE-11 from 350 to 590), so a pass over 500
is likely. The split is planned now, as BE-12 did (its 3.8):

- **Step 1** (`feat/be-06-step-1-cursor-and-limit`, PR to `main`): `parse_limit`,
  `encode_cursor`, `parse_cursor`, the refusal tuples, and the pure tests of
  section 5.1 (`test_cursor_round_trip`, `test_naive_cursor_time_is_refused`,
  the `limit` and `cursor` cases of `test_invalid_limit_is_422` and
  `test_invalid_cursor_is_422` that need no route). No route.
- **Step 2** (PR to `main`, after step 1): `read_statement_page`, the route, the
  route tests and all of `test_statement_list_db.py`.

Branch `feat/be-06-list-statements`, from `origin/main`, PR to `main` if one
step. Decision (delegated, the owner is away): one item, two steps as above
only if the code passes about 650 lines, as BE-12 decided. No migration: the
index of 0004 serves the query (section 8, claim 3).

### 3.9 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add `REFUSED_INVALID_LIMIT` and `REFUSED_INVALID_CURSOR` (3.6); `parse_limit`, `encode_cursor`, `parse_cursor`; the models `StatementListItemView` and `StatementPageView`; `read_statement_page(session, user, limit, after)` with the query of 3.4 |
| `app/api/server/routes/statements.py` | Add `GET /api/statements`, which reads the query by hand (3.1), applies 3.5 and returns `Cache-Control: no-store` |
| `app/api/tests/test_statement_list.py` | New: section 5, no database |
| `app/api/tests/test_statement_list_db.py` | New: section 5, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-06 to In progress, then the PR link, and the `Depends on` cell gains BE-29 (section 6, gap 1). Not changed by this spec |

No migration (the index `ix_statements_user_id_created_at` of 0004 covers the
filter and the first sort key), no setting, no dependency, no change to
`server/main.py`, and no change to `test_access_routes.py`: its
every-route-is-protected test already sends an unauthenticated `GET` to every
route and accepts `401` (section 8, claim 4).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge (deploy)* list: no migration, no deploy. The route is
checked through the test client, with the Access verifier faked.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-24 and BE-29 are merged | `cd app/api && grep -n 'def current_user' server/users.py && grep -n 'class Transaction' server/db/models.py` prints two lines |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected, and `test_access_routes.py` passes unedited |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_statement_list_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_list.py -v` | All pass: `test_list_requires_access`, `test_invalid_limit_is_422`, `test_invalid_cursor_is_422`, `test_cursor_round_trip`, `test_naive_cursor_time_is_refused`, `test_list_response_headers`, `test_list_logs_carry_no_values`, `test_default_limit_is_20`, `test_no_engine_is_503`, `test_query_error_is_503_without_details` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_list_db.py -v` | All pass: `test_newest_first_across_pages`, `test_equal_created_at_is_ordered_by_id`, `test_exact_page_has_no_next_cursor`, `test_fixture_row_values`, `test_pending_review_follows_reviewed`, `test_empty_and_null_total_statements`, `test_one_statement_per_page`, `test_other_users_rows_never_leak`, `test_empty_list_is_200`, `test_new_statement_does_not_shift_pages`, `test_app_role_lists_statements` |
| 5 | The index the query relies on, in the local database: `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select indexdef from pg_indexes where indexname='ix_statements_user_id_created_at'"` | One line, on `(user_id, created_at DESC)` |
| 6 | The plan uses that index: `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "set enable_seqscan = off; set enable_bitmapscan = off; explain select id from portal.statements where user_id = '00000000-0000-4000-8000-000000000000' order by created_at desc, id desc limit 21"` | At least one line contains `ix_statements_user_id_created_at`. The line may be `Index Scan` or `Index Only Scan`; a `Bitmap` scan is excluded by the setting (section 8, claim 2) |

## 5. Tests

Fictitious data only. The db tests import the canonical fixture through
`import_statement` (BE-05) and insert the other statements through the ORM
(`Statement`, `Transaction`) with explicit `created_at` values and names such
as "Fatura Cartão Exemplo, nº 07". Users are made through the BE-24 path with
`tests/access_helpers.py`, with the verifier faked. No call leaves the machine.

### 5.1 `test_statement_list.py` (no database)

The session is the fake of `test_statement_read.py`, extended to answer the
page query from a list of rows. Which app each test uses is in the table; the
Access chain and `get_session` are real wherever the test is about them.

| Test | App | Asserts |
|---|---|---|
| `test_list_requires_access` | Plain `create_app` with the Access verifier faked, no overrides | No token gives `401`, and the page query is never reached |
| `test_invalid_limit_is_422` | Overrides: fake session, `current_user` a `User` | `0`, `101`, `-1`, `1.5`, `abc`, an empty value and a repeated `limit` each give `422` with `invalid_limit`, and the fake session records no query |
| `test_invalid_cursor_is_422` | Overrides, as above | An empty `cursor=`, `!!!`, base64 of `[]`, JSON without `i`, a `t` without offset, an `i` that is not a UUID, a `v` of `2`, a `v` of `true` (a boolean is not the integer 1, so `parse_cursor` checks `type(v) is int`), a 513-character value and a repeated `cursor` each give `422` with `invalid_cursor`, and no query runs |
| `test_cursor_round_trip` | Pure: `encode_cursor` then `parse_cursor` | The timestamp keeps its microseconds and the id is the same; the output has no `=` padding |
| `test_naive_cursor_time_is_refused` | Pure: `parse_cursor` on a cursor whose `t` has no offset | `invalid_cursor` (the `ValueError` of 3.3) |
| `test_list_response_headers` | Overrides, the fake returns two rows | `200` with `Cache-Control: no-store`; `total` is a string (`"11906.35"`) or `null`; `created_at` ends in `Z`; `next_cursor` is a string when a row is left over |
| `test_list_logs_carry_no_values` | Overrides, as above, with a planted name `Fatura Sigilo Exemplo`, a planted total `1234.56`, a request with `?limit=7&cursor=<full cursor>` | The request line has `"route": "/api/statements"`. The planted name and total, the strings `limit=7`, `cursor=` and the full cursor value appear in no line. (Not the `limit` digit alone: timestamps and durations contain digits) |
| `test_default_limit_is_20` | Overrides; the fake returns 25 rows | Without `limit`: `200`, exactly 20 items, and `next_cursor` is a string. The test asserts behavior, not the SQL text |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token | `503` with `database_unavailable` and the BE-24 message |
| `test_query_error_is_503_without_details` | Overrides; a fake session whose `execute` raises `OperationalError` with a host name | `503` with `database_unavailable`; the host is in neither the body nor the log, which holds `database_error` and the class name |

### 5.2 `test_statement_list_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_newest_first_across_pages` | 45 statements with distinct `created_at`. With `limit=20` the pages hold 20, 20 and 5 items, in descending order; `next_cursor` is `null` on the last page; every id appears once across the pages |
| `test_equal_created_at_is_ordered_by_id` | Three statements with the same `created_at`, paged with `limit=1`: they come back in descending `id` order, with no skip and no repeat across the cursor boundaries |
| `test_exact_page_has_no_next_cursor` | Exactly 20 statements with `limit=20`: 20 items and `next_cursor` `null`. With 21, the first page has `next_cursor` and the second has 1 item |
| `test_fixture_row_values` | The canonical fixture imported (BE-05): one item with `total` `"11906.35"`, `transaction_count` 17, `pending_review_count` 2, `created_at` ends in `Z` |
| `test_pending_review_follows_reviewed` | Set `reviewed` true on "Software Gestão Teste" through the ORM: `pending_review_count` goes from 2 to 1 |
| `test_empty_and_null_total_statements` | A statement with no total and no lines (ORM): `total` `null`, `transaction_count` 0, `pending_review_count` 0 |
| `test_one_statement_per_page` | Records every SQL statement the request executes (a `before_cursor_execute` listener on the engine). For 20 statements with 3 lines each and for `limit` of 1, 20 and 100, the request executes exactly two statements in total: the `portal.users` lookup of BE-24, and the one page query of 3.4. The count is flat in the page size, so no statement runs per row. A statement that reads `portal.transactions` on its own would make the count grow with the page and fail |
| `test_other_users_rows_never_leak` | Two users, each with statements. User A's pages contain only A's ids. A cursor taken from A, sent by B, returns only B's rows. B with no statements gets `items` `[]` |
| `test_empty_list_is_200` | A user with no statements: `200`, `{"items": [], "next_cursor": null}` |
| `test_new_statement_does_not_shift_pages` | Fetch page 1, insert a newer statement, fetch page 2 with the cursor: the items are the ones after page 1, with no repeat and no skip |
| `test_app_role_lists_statements` | As `app_backend` (RLS on), the list works with only the grants of BE-28 |

## 6. Open questions

Each question below has a recommendation. The owner is away, so each one is
delegated: the recommendation will be adopted (delegated: the owner is away; the
recommendation will be adopted).

1. **Response shape.** *Recommended: an object, `{"items": [...], "next_cursor": ...}`, not a bare array.* The
   next cursor belongs in the body, next to the items, and the object leaves room
   for later fields without a breaking change. The alternative is a bare array
   with a `Link` header, which the frontend would have to parse. (delegated: the
   owner is away; the recommendation will be adopted)

2. **Is the cursor signed?** *Recommended: no.* Every query filters by the token's
   user, so a forged cursor can only pick a position in the caller's own rows. An
   HMAC would need a new secret setting (for example `PORTAL_CURSOR_KEY`) and a
   `.env.example` entry, for no gain in privacy. The alternative is an HMAC over
   the cursor, adopted if the owner wants a cursor that cannot be edited at all.
   (delegated: the owner is away; the recommendation will be adopted)

3. **A `limit` out of range: refuse or clamp?** *Recommended: refuse with `422 invalid_limit`.* A
   clamp hides a client bug, and the frontend sends fixed values. The alternative is
   to clamp to 1 to 100, which is friendlier to a hand-written URL. (delegated: the
   owner is away; the recommendation will be adopted)

4. **Precision of the cursor and of `created_at`.** *Recommended: the cursor carries the
   microseconds; the response shows `created_at` in seconds, as BE-10 does.* The
   order must use the full value, or two statements in the same second could
   swap or repeat across pages. The alternative is to show microseconds in
   `created_at`, which the screen does not need. (delegated: the owner is away; the
   recommendation will be adopted)

5. **Timezone of `created_at`.** *Recommended: UTC with `Z`, as BE-10.* FE-04 shows
   "02/10/2026 14:12" in Brazilian time. The frontend converts from UTC, and the API
   does not localize. The alternative is a server-side offset, which would tie the
   API to one zone. (delegated: the owner is away; the recommendation will be adopted)

6. **Index for the tie-break.** *Recommended: keep the 0004 index as it is, no migration.*
   It covers `user_id` and `created_at`. The `id` key is sorted incrementally over
   the rows of one `created_at` value, which is rare and small. A new index with
   `id` would need a migration and a reserved revision number, and the reserved
   numbers 0006 to 0009 belong to BE-13, BE-09, BE-07 and BE-04. The check of
   section 4 (6) shows the plan. (delegated: the owner is away; the recommendation
   will be adopted)

### Gaps for the owner

- **Missing dependency (BE-06).** The backlog row lists `BE-24, BE-28`. The query
  reads `portal.transactions` for `transaction_count` and `pending_review_count`,
  so `BE-29` must be in the row too. BE-29 is Done, so nothing waits on it, but
  the row should say it. The spec adds it to its own header; the owner updates
  the backlog row.
- **FE-04's status and name fields.** FE-04's table shows the status ("Classificando",
  "Concluída", "Falhou: ...") and the total for a classifying statement. The status
  comes from BE-07, and FE-04 depends on BE-07 in the backlog, so that is covered.
  The card name ("Cartão Exemplo final 0000") is BE-09, which FE-06 needs, not FE-04.
- **The `items` wrapper** is a new shape for the list. The frontend spec of FE-04
  must name it; this spec is the contract (question 1).

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-24 merged: `current_user` exists | Agent | `cd app/api && grep -n 'def current_user' server/users.py` | One line |
| BE-28 and BE-29 applied locally | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation; the delegated recommendations apply until then |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production
database, no deploy, no migration.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `server/main.py` answers every `RequestValidationError` with `422 invalid_statement`, on any route, so query parameters must be read by hand | *Verified*, `app/api/server/main.py` lines 29 to 32 and 86 | `test_invalid_limit_is_422` (the code is `invalid_limit`, not `invalid_statement`) |
| 2 | The page query uses the index `ix_statements_user_id_created_at` with the `id` tie-break sorted over the page's rows | *Assumed* | Check 6 |
| 3 | The index of 0004 is `(user_id, created_at DESC)`, so no migration is needed | *Verified*, `app/api/migrations/versions/0004_statements.py` lines 52 to 58, and `server/db/models.py` | Check 5 |
| 4 | The every-route-is-protected test covers `GET /api/statements` with no edit: an unauthenticated `GET` gives `401` | *Verified*, `app/api/tests/test_access_routes.py` lines 82 to 100 (the path has no parameter, so no sample id is needed) | Check 1 |
| 5 | Access is enforced for the new route by `FastAPI(dependencies=[Depends(require_access)])` | *Verified*, `app/api/server/main.py` line 65 | `test_list_requires_access` |
| 6 | `psycopg` returns `created_at` with its microseconds, so the cursor round-trips exactly | *Assumed* | `test_cursor_round_trip` (pure) and `test_equal_created_at_is_ordered_by_id` (db) |
| 7 | A `LEFT JOIN` with `COUNT(t.id)` gives a statement with no lines `0` and `0` | *Verified* by SQL semantics; the same pattern is in BE-12 (3.3) | `test_empty_and_null_total_statements` |
| 8 | The request log writes no query string (so the cursor and the limit are not logged) | *Verified* in the rule of `docs/BACKEND_GUIDELINES.md` (Logging); the log line itself is not read here | `test_list_logs_carry_no_values` |
| 9 | The dependency overrides of the BE-24 tests work for this route as they do for `/api/me` | *Assumed*, as in BE-10 (claim 9) | First run of `test_statement_list.py` |
| 10 | The fake session of `test_statement_read.py` (BE-10) can answer the page query through `execute` with rows, as BE-12's fake does (claim 8 there) | *Assumed*. `test_statement_read.py` is not read by this spec's author; it is BE-10's file, and BE-10 is merged | First run of `test_statement_list.py`; if the fake differs, the test file carries its own fake |

## 9. Notes for the implementer

- The page is one statement; the pending counts are not a second query and not a Python loop over lines.
- Fetch `limit + 1` rows. Keep `limit` of them. The extra row only decides `next_cursor`.
- Build the cursor from the last **kept** row, with its full-precision `created_at`.
- `parse_limit` and `parse_cursor` are pure functions, so their tests need no database.
- Do not let the cursor or the limit reach a log line or an error message.

## Amendments before approval (2026-11-21)

- Implementation order: BE-06 is built after BE-09 and BE-07 (owner-delegated order), so its list item also returns `card_name`, `card_last4` (BE-09) and `status`, `failure_code`, `failure_message` (BE-07), with the same types as BE-10's header. Its Depends on gains BE-09 and BE-07, and BE-29. Tests assert these fields on the fixture import (card `Cartão Exemplo` / `0000`, status `ready`, `failure_code` null) and on a failed statement set through `set_status`.
