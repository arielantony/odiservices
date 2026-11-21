# Spec — BE-08 Retry a failed extraction

| | |
|---|---|
| **Backlog** | Feature: Statement upload and processing › Backend › BE-08 |
| **Story** | FE-05 (Retry a failed statement: the "Tentar de novo" action). The scenarios are read from `docs/stories/categorizer-home/FE-05-retry-failed-statement.feature` |
| **Prototype** | `docs/prototypes/portal/v3.html#home` |
| **Depends on** | BE-03 (extraction runs server-side), BE-04 (the encrypted upload blob), BE-07 (status and failure code). All three are Draft today: this spec is approved only with them merged, and section 8 lists the interfaces it takes from each |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

A statement whose extraction failed (`status = 'failed'`) goes back into
classification without a new upload. `POST /api/statements/{statement_id}/retry`
checks that the statement is the signed-in user's and failed, loads the encrypted
PDF kept by BE-04, moves the statement to `processing` in one conditional update,
and starts the BE-03 extraction in the background. It answers `202` at once. Two
concurrent retries of the same statement cannot both run: only one update wins.

## 2. Scope

**In scope**

- `POST /api/statements/{statement_id}/retry` and the function behind it
  (`claim_retry`, in a new module `app/api/server/retry.py`), with the background
  start.
- The conditional update that claims the statement (3.3).
- The refusals: `404 statement_not_found`, `409 statement_not_failed`,
  `409 upload_not_available`, and the processing limit answer of BE-03 (3.5).
- Tests (section 5).

**Out of scope**

- The extraction itself, its prompt, its import and its failure codes: BE-03.
- Keeping, encrypting and wiping the PDF blob: BE-04. BE-08 only reads it.
- The status column, the failure code vocabulary and the list fields: BE-07.
  BE-08 writes the status through BE-07's `set_status`.
- A limit on the number of attempts: not built (section 6, question 1).
- The "Tentar de novo" button, the row status text and the polling of the list:
  FE-04 and FE-05. The browser calls the route and then the list again.
- Deleting a failed statement and its blob: BE-15.

## 3. Design

### 3.1 The route

`POST /api/statements/{statement_id}/retry`, behind the Access check (BE-23,
application-wide) and `Depends(current_user)` (BE-24), as BE-10 and BE-11 are.
The statement is found by its id and the user in the token, never by a user id.
The id is declared as `str` and parsed with `uuid.UUID(...)` in the handler, so a
malformed id is a `404`, not a `422`. There is no body. The route is a new
segment under the statement, so it does not collide with BE-10's `GET`.

### 3.2 The response

`202 Accepted`, with `Cache-Control: no-store`:

```json
{"id": "5f0c2d9e-8a41-4b7e-9d36-2c1a7e8b0f14", "status": "processing"}
```

- `status` is always `"processing"`. The extraction runs after the response, so
  the browser reads `GET /api/statements/{statement_id}` (BE-10) or the list
  (BE-06) to follow it, as FE-14 does.
- The response names no file, no failure text and no value.

### 3.3 Claiming the statement (the atomic part)

The claim is one conditional update through BE-07's `set_status`, with an
`expected` status:

```sql
UPDATE portal.statements
   SET status = 'processing', failure_code = NULL
 WHERE id = :sid AND status = 'failed'
RETURNING id;
```

`set_status(..., expected='failed')` returns `True` when the row was updated and
`False` when no row matched. Two concurrent retries both read `failed`; the
database lets one update succeed. The second one's update matches no row, because
the first has already set `processing`, and it gets `409 statement_not_failed`.
Nothing is decided in Python between the read and the update, so no lock is held
across the Anthropic call.

The flow in `claim_retry(session, user, statement_id)`, in this order:

1. `owned_statement(session, user, statement_id)` (BE-10). No row: `404`.
2. `statement.status != 'failed'`: `409 statement_not_failed`.
3. `load_upload(session, statement_id)` (BE-04). `None`: `409 upload_not_available`.
   The blob is only read here, not decrypted.
4. The per-user processing limit of BE-03 (3.5). Refused: its answer.
5. `set_status(..., 'processing', failure_code=None, expected='failed')`. `False`:
   re-read the statement. Missing now: `404`. Otherwise: `409 statement_not_failed`.
6. Commit. Only now is the background task added.

The background task is `run_extraction(engine, statement_id, client, model)` (BE-03), added with
FastAPI's `BackgroundTasks`. It runs after the response has been sent. The request
session is closed by then, so `run_extraction` opens its own session, as BE-03
defines.

### 3.4 The blob

The retry does not write the blob. `run_extraction` loads it again through
`load_upload` and decrypts it. If the blob is gone between steps 3 and 6 (a delete
races the retry), `run_extraction` sets the statement back to `failed` with the
failure code `upload_not_available` and stops. That is the only way the background
task fails without BE-03's extraction having run. On success, BE-03 wipes the blob,
as it does for a first upload (BE-04).

### 3.5 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors). The refusals use the
same shape as the constants that `server/statements.py` already defines, such as
`REFUSED_NOT_FOUND` (not re-read for this spec: checked at implementation).

| Status | `code` | `message` (pt-BR) | When |
|---|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged | No or invalid token; no user row |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` (BE-10, unchanged) | Unknown, malformed, another user's, or deleted during the claim |
| 409 | `statement_not_failed` | `Só é possível tentar de novo uma fatura que falhou.` | Status is `processing` or `ready`, or a concurrent retry won the claim |
| 409 | `upload_not_available` | `O PDF desta fatura não está mais disponível. Envie a fatura novamente.` | No blob: wiped, or never kept |
| 429 | from BE-03 | from BE-03 | The per-user processing limit is reached |
| 503 | `database_unavailable` | from BE-24, unchanged | Also for a `DBAPIError` in any query of the route; the log carries the class name only |

Order of answers: `404` before `409`, and `statement_not_failed` before
`upload_not_available`. A `ready` statement with no blob (the normal case after a
success) therefore answers `statement_not_failed`, not `upload_not_available`.

The `409 statement_not_failed` on the losing side of a race has the same body as
the one for a ready statement: the client cannot tell them apart, and does not
need to.

### 3.6 Logging

BE-21's request log is the only log for the request, with the route template
`/api/statements/{statement_id}/retry`. The route writes one event
`statement_retry_started` with the statement id and the user id (ids only, as the
BE-21 rule allows), and one `database_error` line on a `DBAPIError`, with the class
name only. The file name, the blob and the extraction result are never logged.

### 3.7 Steps

One step, estimated at 250 to 350 lines with the tests. One PR to `main`, branch
`feat/be-08-retry-extraction`, from `origin/main`. It stays under 500 lines and
needs no split.

### 3.8 Files

| File | Change |
|---|---|
| `app/api/server/retry.py` | New: `claim_retry(session, user, statement_id)`, and the refusal constants of 3.5 |
| `app/api/server/routes/statements.py` | Add `POST /api/statements/{statement_id}/retry` (202), calling `claim_retry` and adding `run_extraction` as a background task |
| `app/api/tests/test_statement_retry.py` | New: section 5, no database |
| `app/api/tests/test_statement_retry_db.py` | New: section 5, marker `db`, local Postgres only (section 5.2) |
| `docs/BACKLOG.md` | At implementation: BE-08 to In progress, then the PR link. Not changed by this spec |

No migration: the columns of BE-07 and the table of BE-04 already exist when this
item starts. No setting, no dependency, no change to `server/main.py`. The
every-route test of BE-23 (`test_access_routes.py`) covers the new route with no
edit, because it fills the path parameter with a sample id.

## 4. Verification

All checks run when the item merges, with only BE-08 and its three dependencies,
against the local Postgres (`make db-up`). There is no *After merge (deploy)* list:
no migration, no deploy.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-03, BE-04 and BE-07 are merged, and BE-10 is | `cd app/api && grep -rn "def run_extraction\|def load_upload\|def set_status\|def check_processing_limit" server/ \| wc -l` prints `4`; and `grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_retry.py -v` | All pass: the thirteen tests of section 5.1 |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_access_routes.py -v` | All pass, including the every-route test, which now covers `/retry` |
| 4 | `cd app && make db-up && cd api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_retry_db.py -v` | All pass: `test_concurrent_claims_one_wins`, `test_retry_claim_leaves_other_statements_alone` |
| 5 | Scenario FE-05, server side, on the fixture's shape: `cd app/api && .venv/bin/python -m pytest tests/test_statement_retry.py::test_retry_puts_failed_statement_back_to_processing -v` | Passes: `202`, the status is `processing`, and the failure code is cleared |

The FE-05 scenarios are browser scenarios (`Tentar de novo` and the row text).
They belong to FE-05 and are not checked here. Check 5 covers the server side of
the second scenario.

*Pending validation* (owner, real PDF, with the owner present): upload a real
statement that fails, press "Tentar de novo" in the running portal, and confirm
it reaches `ready` or `failed` again. Record "validated on <date>", with no data.

## 5. Tests

Fictitious data only. The fixture is `app/fixtures/statement-example-2026-09.json`
for the success path, and a failed statement is built in memory from it with
`failure_code` set. The fake session, the fake extraction client and the in-memory
blob store are plain Python objects. No call leaves the machine: no Anthropic, no
Supabase, no Cloudflare Access. Access and the user row use `tests/access_helpers.py`
and the BE-24 pattern, with the verifier faked.

### 5.1 `test_statement_retry.py` (no database)

The fake session answers `owned_statement` with a statement object (status,
user id, id). The fake `load_upload`, `set_status` and `check_processing_limit`
are monkeypatched on `server.retry`, so the route runs the real `claim_retry`.

| Test | Asserts |
|---|---|
| `test_retry_requires_access` | No token gives `401`, and no fake is called |
| `test_malformed_id_is_404` | `abc-123`, a uuid one character short, and `%20` each give `404` with `statement_not_found`; no fake is called |
| `test_other_users_statement_is_404` | A statement of another user gives the same `404` body and headers as an unknown uuid4, except `X-Request-Id` |
| `test_ready_statement_is_409_not_failed` | `status = 'ready'` gives `409` with `statement_not_failed`; `set_status` is never called |
| `test_processing_statement_is_409_not_failed` | `status = 'processing'` gives `409` with `statement_not_failed` |
| `test_missing_blob_is_409_upload_not_available` | `status = 'failed'`, `load_upload` returns `None`: `409` with `upload_not_available`, the pt-BR message of 3.5, and `set_status` is never called |
| `test_status_is_checked_before_blob` | `status = 'ready'` and no blob gives `statement_not_failed`, not `upload_not_available` |
| `test_retry_puts_failed_statement_back_to_processing` | `failed` with a blob: `202` with `{"id", "status": "processing"}`, `set_status` called once with `expected='failed'` and `failure_code=None`, `Cache-Control: no-store` |
| `test_claim_lost_to_a_concurrent_retry_is_409` | `set_status` returns `False` and the re-read shows `processing`: `409` with `statement_not_failed`, and the background task is not added |
| `test_claim_lost_to_a_delete_is_404` | `set_status` returns `False` and the re-read finds no row: `404` with `statement_not_found` |
| `test_processing_limit_refusal_is_passed_through` | `check_processing_limit` refuses: the status and body of BE-03 are returned, `set_status` is never called |
| `test_retry_logs_carry_no_values` | The request line holds `"route": "/api/statements/{statement_id}/retry"` and no id. The event `statement_retry_started` holds the ids only. A planted file name `Fatura Teste.pdf` and a planted failure text appear in no line |
| `test_database_error_is_503_without_details` | `owned_statement` raises `OperationalError` with a host name: `503` with `database_unavailable`; the host is in neither the body nor the log |

The background task is checked by replacing `run_extraction` with a recording
fake: the test asserts it was called once with the statement id and the fake client,
after the response was built. The test does not run the extraction.

### 5.2 `test_statement_retry_db.py` (marker `db`, local Postgres)

The only test here that uses a real database. It is local Postgres as `app_backend`,
as the other `db` tests are, and it calls no external service. It is a deliberate
exception to "fakes only": a fake cannot show that the conditional update is
atomic. The owner may refuse it, in which case check 4 is dropped and 3.3 stays
unverified (section 6, question 3).

| Test | Asserts |
|---|---|
| `test_concurrent_claims_one_wins` | Two threads each call `set_status(..., expected='failed')` on the same failed row, released together with a barrier: exactly one returns `True`, and the row ends `processing` |
| `test_retry_claim_leaves_other_statements_alone` | A second failed statement of the same user keeps `failed` and its failure code after the claim of the first |

## 6. Open questions

Each question has a recommendation. The owner is away: each recommendation is
adopted as written (delegated: the owner is away; the recommendation will be
adopted).

1. **A cap on attempts.** *Recommended: no cap and no counter. Rate-limit the
   retry through the per-user processing limit of BE-03 (step 4 of 3.3).*
   A counter needs a column and a number nobody has chosen, and a fixed cap
   blocks a PDF that failed for a transient reason. The processing limit bounds
   how many extractions run at once per user. It does not bound how often a user
   retries. A retry loop on a PDF that always fails costs one Anthropic call each
   time, and nothing here stops it. The owner should know this: the cheap later
   fix is a cooldown (refuse a retry within N seconds of `updated_at`), a single
   `429`, and it needs no migration.
2. **Where the blob is read: in the route or in the background task.**
   *Recommended: the route reads it once (step 3) to answer `409` before any
   change, and the background task reads it again to decrypt it.* The route's
   answer is then right, and a blob wiped after the claim still ends in a clear
   `failed`, through 3.4.
3. **The database test of 5.2.** *Recommended: keep it. It is the only test of the
   atomicity claim, and it uses local Postgres only.* The alternative is fakes
   only, which proves that the code asks for a conditional update, not that the
   database grants it.
4. **The status code of the success answer.** *Recommended: `202`, with the status
   `processing` in the body, as the work continues after the response.* A `200`
   would suggest the statement is already classified.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-03 merged: `run_extraction`, the injectable client and the processing limit exist | Agent | `cd app/api && grep -rn "def run_extraction\|def check_processing_limit\|def get_extraction_client" server/ \| wc -l` | `3` |
| BE-04 merged: `load_upload` exists, and the table `portal.statement_uploads` is migrated (`0009`) | Agent | `cd app/api && grep -rn "def load_upload" server/ \| wc -l` and `cd app && make db-current` | `1`, then `0009 (head)` |
| BE-07 merged: `set_status` with `expected`, and `statements.status` and `failure_code` exist (`0008`) | Agent | `cd app/api && grep -rn "def set_status" server/ \| wc -l` and `cd app && make db-current` | `1`, then `0009 (head)` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0009 (head)` |
| The categories are seeded (10, positions 1 to 10) | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for the `db` test) | Owner | `docker info >/dev/null && echo ok` | `ok` |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production
database, no deploy, no migration.

**Cost.** None to build. At run time each retry is one Anthropic call (section 6,
question 1).

## 8. Assumptions to verify

The interfaces below come from specs that are not written yet (BE-03 is Draft
with no spec). Each one is recorded here so that BE-03, BE-04 and BE-07 can match
it, or this spec is updated before any code is written.

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | BE-03 provides `run_extraction(engine, statement_id: uuid.UUID, client, model) -> None`, which opens its own session and sets `ready` or `failed` | *Assumed*: required from BE-03's spec | Check 0, then the recording fake of 5.1 |
| 2 | BE-03 provides an injectable client through a dependency `get_extraction_client`, overridable in tests | *Assumed*: required from BE-03's spec | Check 0 |
| 3 | BE-03 provides `check_processing_limit(session, user)`, which raises a refusal carrying BE-03's `429` answer when the user has too many `processing` statements | *Assumed*: required from BE-03's spec. The name is a proposal | Check 0, `test_processing_limit_refusal_is_passed_through` |
| 4 | BE-04 provides `load_upload(session, statement_id) -> bytes \| None`, the ciphertext, and does not decrypt it | *Assumed*: required from BE-04's spec. The table is `portal.statement_uploads` (BE-04's cross-item decision) | Check 0 |
| 5 | BE-07 provides `set_status(session, statement_id, status, *, failure_code=None, expected=None) -> bool`. With `expected`, it is `UPDATE ... WHERE status = :expected` and returns whether a row changed. It flushes and does not commit | *Assumed*: this is an amendment to BE-07's spec (`expected`), which must be proposed to the owner there. The BE-07 spec does not have it yet | Check 4 (`test_concurrent_claims_one_wins`) |
| 6 | BE-10's `owned_statement(session, user, id)` returns the statement row with `status` once BE-07 adds it | *Assumed*: BE-10 is Done and `owned_statement` is verified in BE-12's spec (section 3.5); the `status` attribute comes from BE-07 | `test_ready_statement_is_409_not_failed` |
| 7 | Postgres runs `UPDATE ... WHERE status = 'failed'` as one statement, so two concurrent updates on one row serialize: the second matches no row under READ COMMITTED | *Verified* as a property of Postgres's row locking (an `UPDATE` re-checks its `WHERE` after waiting on the row lock) | Check 4 |
| 8 | Starlette matches `{statement_id}` to one path segment, so `/retry` is not taken by BE-10's route | *Assumed* | `test_retry_requires_access` and the route test of 5.1 (a `202`, not a `404`) |
| 9 | `BackgroundTasks` runs after the response is sent, and the request's session is closed by then | *Verified* in FastAPI's documented behavior for dependencies with `yield`, which close after the response. The background task must not use the request session | `test_retry_puts_failed_statement_back_to_processing` (the recording fake is called after the response) |

## 9. Notes for the implementer

- The claim is the only place that decides who wins. Do not add a Python check of
  `status` between the read and the update as a substitute: it is the race.
- `claim_retry` returns the statement id and nothing else. The route builds the
  `202` body from it.
- Keep `run_extraction` out of `server/retry.py`. The route imports it from BE-03's
  module, so BE-08 has no extraction code of its own.
- If BE-03's spec names the processing limit differently, or does not provide one,
  step 4 of 3.3 changes and this spec is updated before the code continues.

## Amendments before approval (2026-11-21)

- The names this spec uses are fixed by the BE-03, BE-04 and BE-07 specs: `run_extraction(engine, statement_id, client, model)` and `check_processing_limit(session, user)` (BE-03), `get_extraction_client` (BE-03), `load_upload` (BE-04), and `set_status(..., expected=..., commit=...) -> bool` (BE-07, amended for this item). The failure code `upload_not_available` is in BE-07's vocabulary.
