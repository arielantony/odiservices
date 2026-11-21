# Spec — BE-16 Provide display labels for the categories

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-16 |
| **Story** | FE-07 (the legend shows the labels) and FE-08 (the lane titles). Both consume this item |
| **Prototype** | `docs/prototypes/portal/v3.html#board` |
| **Depends on** | BE-30 (Done, #79 and #80): the `portal.categories` table with its pt-BR labels. BE-24 (Done): `Depends(current_user)` for the signed-in person |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

The board shows each category by its name in Brazilian Portuguese ("Fornecedor",
"Despesas financeiras"), not by its stored code (`FORNECEDOR`,
`DESPESAS FINANCEIRAS`). The labels already live in `portal.categories.label`
(BE-30). `GET /api/categories` returns the categories, in their fixed order, as
`{code, label, position}`. The frontend maps a code to its label through this
list, so the label text is never copied into the browser bundle. The route is
read-only, needs the signed-in person (as every board route does), and reads one
table of ten rows.

This item answers the question that BE-12 (section 6, question 7) and the
backlog (BE-16 row) left open: the **API** owns the mapping from code to label,
and the list is its source. BE-10 and BE-12 keep returning codes only.

## 2. Scope

**In scope**

- `GET /api/categories`, its response model and the function behind it
  (`list_categories`).
- The order: by `position`, in the query.
- The access rule (the Access check of BE-23 and `Depends(current_user)` of
  BE-24) and the error answers of section 3.5.
- Tests (section 5).

**Out of scope**

- The labels themselves and their text: BE-30 (seeded in migration `0003`). This
  item does not change a label. A new or renamed category is a row changed by the
  owner (BE-30, 6.2), not an endpoint.
- The code-to-label mapping in the browser, the legend and the lanes: FE-07 and
  FE-08. A label missing from this list is a frontend error, not a fallback
  to the code.
- A per-category count, total or share: BE-12.
- The classification rules and `auto_assign`: the classifier items. `auto_assign`
  is not returned (question 3).
- Any change to the database: no migration (section 3.3).

## 3. Design

### 3.1 The route

`GET /api/categories`, in a new module `server/routes/categories.py`. It takes
`user: User = Depends(current_user)` and `session: Session = Depends(get_session)`,
as `GET /api/me` and BE-10 do. The Access check of BE-23 already runs on every
route. `current_user` adds the person (BE-24): the route answers only for a
signed-in person with a `users` row, which is the rule of every board route
(question 2).

There is no path parameter, body or query string. The response is the same for
every caller, so nothing varies with the user and no user id is read.

### 3.2 The response

`200`, with `Cache-Control: no-store` (question 4):

```json
[
  {"code": "FORNECEDOR", "label": "Fornecedor", "position": 1},
  {"code": "OPERACIONAL", "label": "Operacional", "position": 2},
  {"code": "MARKETING/COMERCIAL", "label": "Marketing/Comercial", "position": 3}
]
```

The example is abbreviated: the real list has ten elements, the rows of
`portal.categories`, in the order of 3.4.

- A JSON array at the top level, one element per row. The shape is the same
  for every caller.
- Each element has exactly three keys: `code` (text, as stored), `label` (text,
  pt-BR, as stored) and `position` (integer, 1 to 10 for the seeded set). No
  other key (question 3).
- The list is not paginated. The table has ten rows, and the owner adds
  categories by hand (BE-30). A paginated list would be a contract for no
  purpose.
- An empty table gives `[]` with `200`. It cannot happen with BE-30's seed, but
  the route does not invent rows.
- The labels are returned as stored. The route does not trim, translate or
  capitalize them.

### 3.3 Data and migration

No migration. The table, its seed and its row-level security are BE-30's
(`0003_categories`, verified in `app/api/migrations/versions/0003_categories.py`):

- `SELECT` for `app_backend` comes from the default privileges of `0001`
  (verified: `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE, DELETE`).
  BE-30 then revokes `INSERT, UPDATE, DELETE` on `portal.categories` from
  `app_backend`, so the route is read-only by grant as well as by code.
- The row-level security policy `backend_only` (`enable_backend_only_rls`,
  verified in `migrations/helpers.py`) lets `app_backend` see every row. The route
  runs as `app_backend`, so it sees all ten rows.

Nothing new is granted. The migration-tests drift check (BE-31) is unchanged,
because no model or migration changes. Migration head stays `0005`.

### 3.4 The query and the order

```python
def list_categories(session: Session) -> list[CategoryView]:
    rows = session.scalars(select(Category).order_by(Category.position)).all()
    return [CategoryView(code=r.code, label=r.label, position=r.position) for r in rows]
```

The order is set in SQL (`ORDER BY position`), not in Python, so the database
returns the lanes in their fixed order. The order is not alphabetical and not by
code: `FORNECEDOR` (position 1) comes first and `OUTROS` (position 10) last, and
the test of section 5 checks that the response is not sorted by code.

`CategoryView` is a Pydantic model in `server/categories.py` with the three fields
of 3.2. It is the only shape the route returns, so a column added to the table
later is not exposed by accident.

The function runs in the threadpool, as the BE-10 route does
(`run_in_threadpool(list_categories, session)`).

### 3.5 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 503 | `database_unavailable` | from `DATABASE_UNAVAILABLE` (BE-24), unchanged. Also for a `DBAPIError` in the query; the log carries the class name only |

There is no `404`: the route has no id. A `DBAPIError` is caught in the route,
logged with `log_event("WARNING", "database_error", error=type(exc).__name__)`
and raised as `AccessError(*DATABASE_UNAVAILABLE)`, as in BE-10.

### 3.6 Logging

The request log of BE-21 is the only line. It records the route template,
`/api/categories`. No label, code or position is logged, and the query has no
parameter to log.

### 3.7 Steps

One step, about 180 lines with the tests, under the limit. Branch
`feat/be-16-category-labels`, from `origin/main`, PR to `main`. No *After merge
(deploy)* step (section 4).

### 3.8 Files

| File | Change |
|---|---|
| `app/api/server/categories.py` | New: `CategoryView` and `list_categories(session)` |
| `app/api/server/routes/categories.py` | New: `GET /api/categories` |
| `app/api/server/main.py` | Import the `categories` router and `include_router` it, next to `statements` |
| `app/api/tests/test_categories_route.py` | New: section 5.1, no database |
| `app/api/tests/test_categories_route_db.py` | New: section 5.2, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-16 to In progress, then the PR link. Not changed by this spec |

No migration, no setting, no dependency, and no change to
`tests/test_access_routes.py`. The every-route test loops over every module of
`server/routes/`, so the new module is covered with no edit (section 8, claim 2).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`) and
BE-30 and BE-24 merged. There is no *After merge (deploy)* list: no migration and
no production change. The route is read-only, and the owner's normal deploy
ships it like any other API route. No check needs BE-13, BE-12 or the frontend.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-30 is merged and the ten rows are seeded | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` prints `10` |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_categories_route_db.py` |
| 3 | `cd app/api && grep -n '"/api/categories"' server/routes/categories.py` | One line |
| 4 | `cd app/api && .venv/bin/python -m pytest tests/test_categories_route.py -v` | All pass: `test_categories_requires_access`, `test_no_engine_is_503`, `test_query_error_is_503_without_details`, `test_labels_equal_the_seeded_labels`, `test_query_orders_by_position_in_sql`, `test_response_shape_and_headers` |
| 5 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_categories_route_db.py -v` | All pass: `test_labels_match_the_seed_in_position_order`, `test_order_is_position_not_code` |
| 6 | `cd app/api && .venv/bin/python -m pytest tests/test_access_routes.py::test_every_route_is_protected_except_the_list -v` | Passes. The new route answers `401` (or `405`) to every method with no token |
| 7 | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select code, label, position from portal.categories order by position;"` | Ten lines, from `FORNECEDOR|Fornecedor|1` to `OUTROS|Outros|10`, the labels of the seed (BE-30, 3.1) |
| 8 | `git diff --stat origin/main -- app/api \| tail -1` | Fewer than 500 changed lines |

Checks 4 and 5 cover the story's needs: the legend and the lanes read the label
of each code from this list (FE-07 "Investimento", "Fornecedor" in FE-08), and the
order of the list is the order of the lanes.

## 5. Tests

Fictitious data only. The categories are the business's own list, not personal
data, so the labels come from the seed itself and no statement is involved. No
call leaves the machine. Access uses `tests/access_helpers.py` with the verifier
faked, as in BE-12.

### 5.1 Unit (`test_categories_route.py`, no database)

The session is a fake whose `scalars` returns the rows of the seed, built from
the migration's `SEED` constant (imported as in `test_categories.py`). The rows
are returned in position order, as the SQL of 3.4 would return them.

| Test | App | Asserts |
|---|---|---|
| `test_categories_requires_access` | Plain `create_app` with the Access verifier faked, no overrides | No token gives `401`; the fake session is never reached |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token | `503` with `database_unavailable` |
| `test_query_error_is_503_without_details` | Overrides: a session whose `scalars` raises `OperationalError` with a host name | `503` with `database_unavailable`; the host is in neither the body nor the log |
| `test_labels_equal_the_seeded_labels` | Overrides: `current_user` a `User`, the fake session with the seed rows | The response's `(code, label, position)` list equals `[(c, l, p) for p, (c, l, _) in enumerate(SEED, 1)]` |
| `test_query_orders_by_position_in_sql` | Pure: compile `select(Category).order_by(Category.position)` for the PostgreSQL dialect | The compiled text ends with `ORDER BY portal.categories.position` (the real order is checked in 5.2) |
| `test_response_shape_and_headers` | Overrides, as above | `200`; `Cache-Control: no-store`; a JSON array of ten objects with exactly the keys `code`, `label`, `position`; no `auto_assign` |

### 5.2 `db` (`test_categories_route_db.py`, local Postgres, as `app_backend`)

The client is built as in `test_statement_read_db.py`: the app engine from
`PORTAL_DATABASE_URL` under `app_backend`, the verifier faked, the user row from
the BE-24 pattern.

| Test | Asserts |
|---|---|
| `test_labels_match_the_seed_in_position_order` | `GET /api/categories` returns the ten rows of `SEED` in order: each `code`, `label` and `position` equal the seed's, with `position` 1 to 10 |
| `test_order_is_position_not_code` | The codes of the response are not in alphabetical order: `FORNECEDOR` first, `OUTROS` last, so an `ORDER BY code` would fail this test |
| `test_response_equals_the_table` | The response equals `select code, label, position from portal.categories order by position` run as the owner (the migration's owner role, as in `test_categories_db.py`) |

Fixtures: the migrated test database and the helpers of `test_migrations_db.py`
(`migrated`, `owner`, `as_role`), as `test_categories_db.py` imports them.

## 6. Open questions

Each question has a recommendation. The owner is away, so each one is decided
by its recommendation (delegated: the owner is away; the recommendation will be
adopted).

1. **Where does the code-to-label mapping live: the API or the frontend?**
   *Recommended: the API. `GET /api/categories` returns the label from
   `portal.categories.label` (delegated: the owner is away; the recommendation
   will be adopted).* The labels are data the owner maintains (BE-30). A frontend
   constant would be a second copy, which BE-30 removed from `ask_pdf.py` and
   `kanban/app.js`. The alternative is a constant in the browser bundle,
   `Record<code, label>`. It saves one request, and it drifts from the table when
   a category is added. This is the decision the backlog's BE-16 row asks for,
   and the one BE-12 assumed.
2. **Does the route need the signed-in person, or only the Access check?**
   *Recommended: `Depends(current_user)` (BE-24), as the board routes do
   (delegated: the owner is away; the recommendation will be adopted).* The
   categories are not the person's data, so the route could skip `current_user`.
   The rule of the board is one rule, though: a route answers a person with a
   `users` row, and the first call creates it. The alternative is
   `Depends(require_access)` (BE-23): the same protection against the outside,
   without the database read of the user row.
3. **Does the response carry `auto_assign`?** *Recommended: no (delegated: the
   owner is away; the recommendation will be adopted).* No story needs it: the
   legend and the lanes show a label and a code. The classifier reads the table
   itself. The field can be added later as an additive key, and the frontend
   ignores unknown keys.
4. **`Cache-Control`.** *Recommended: `no-store`, as every other API response
   (delegated: the owner is away; the recommendation will be adopted).* The list
   changes when the owner adds a category, and `no-store` keeps the portal's rule
   with no exception. The payload is a few hundred bytes.

### Gaps for the owner

These are gaps between the backlog, the stories and this spec. This spec does
not change them. It records them for the owner to decide.

- **The backlog's BE-16 row** lists BE-30 as its only dependency. This spec also
  depends on BE-24 (the `current_user` dependency). Add BE-24 to the row when the
  spec is approved.
- **FE-07 does not depend on BE-16.** Its legend shows the labels ("Investimento",
  "Fornecedor" in its scenarios), but its backlog row lists BE-12 only (the gap
  of BE-12, section 6). The backlog should list BE-16 for FE-07, as it does for
  FE-08.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-30 merged: the ten categories are seeded | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| BE-24 merged: `current_user` exists | Agent | `cd app/api && grep -n "def current_user" server/users.py` | One line |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded: the recommendations are adopted (delegated) |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production
database, no migration, no deploy.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | The route takes the person as `Depends(current_user)` and the session as `Depends(get_session)`, as BE-10 does | *Verified*, `server/routes/statements.py` (`get_statement`) and `server/users.py` (`current_user`, line 96) | Check 4 |
| 2 | The every-route-is-protected test loops over every module of `server/routes/` and needs no edit for a new one | *Verified*, `app/api/tests/test_access_routes.py`, `test_every_route_is_protected_except_the_list` (`pkgutil.iter_modules` over `server.routes`) | Check 6 |
| 3 | No route already uses `/api/categories` | *Verified*: `grep -rn "api/categories" app/api/server app/api/tests` finds nothing (2026-11-21) | Check 3 returns one line |
| 4 | `DATABASE_UNAVAILABLE` in `server/db/session.py` and `log_event` in `server/users.py` are the helpers BE-10 uses for `503` | *Verified* (BE-10's `get_statement`, lines 105 to 110) | Check 4, `test_query_error_is_503_without_details` |
| 5 | The seed of `0003_categories.py` has the labels of section 5 and the positions 1 to 10 | *Verified*, the file's `SEED` list and `enumerate(SEED, start=1)` | Check 7 |
| 6 | `select(Category).order_by(Category.position)` compiles to `ORDER BY portal.categories.position` in the PostgreSQL dialect | *Assumed* | `test_query_orders_by_position_in_sql` |
| 7 | A fake session whose `scalars` returns a list works with `session.scalars(...).all()` | *Assumed* (the fakes of BE-10 and BE-12 use `execute`/`scalars` in the same way) | First run of `test_categories_route.py` |

## 9. Notes for the implementer

- The order is in SQL. Do not sort in Python: the database owns the position,
  and the test of 5.2 checks the database's order.
- `CategoryView` is the only shape the route returns. Do not return the ORM
  row: a column added later would leak.
- No label is hard-coded in the server either. The route reads the table, and
  the tests take the expected labels from the migration's `SEED`, which is the
  seed itself.
