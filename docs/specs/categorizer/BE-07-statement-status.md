# Spec — BE-07 Track each statement's processing status and failure reason

| | |
|---|---|
| **Backlog** | Feature: Statement upload and processing › Backend › BE-07 |
| **Story** | FE-04 (status column: "Classificando", "Concluída", "N para revisar", "Falhou: <reason>"), FE-05 ("Tentar de novo"), FE-14 (follow processing until the board opens) |
| **Prototype** | `docs/prototypes/portal/v3.html#home` (the status labels and the failed row) |
| **Depends on** | BE-28 (Done). Also BE-10 (Done), whose response it extends, and, for the migration numbers only, BE-13 (`0006`) and BE-09 (`0007`), see section 6, question 1 |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

A statement is not always ready. Between the upload and the import it is
being classified, and an extraction can fail. The list (FE-04) and the board
(FE-14) need to know which state a statement is in, and why it failed, so the
person knows whether to wait, to open it or to retry (FE-05). This item adds
the state to the table, a fixed vocabulary of failure codes with a pt-BR
reason for each, and the two fields to the statement read of BE-10. It also
adds an internal function that sets the state, which BE-03 (the extraction) and
BE-08 (the retry) will call. No route writes the state.

## 2. Scope

**In scope**

- Migration `0008_statement_status`: the columns `status` and `failure_code`
  of `portal.statements`, their checks, and the backfill of existing rows.
- The ORM model `Statement` gets the two columns.
- The vocabularies (`STATUSES`, `FAILURE_CODES`) and their pt-BR messages
  (`FAILURE_MESSAGES`), in `server/statements.py`.
- The internal function `set_status(session, statement_id, status,
  failure_code=None)`, with its checks, tested. No route calls it.
- The two new fields `status` and `failure_code` and the derived
  `failure_message` in BE-10's `StatementView` (`GET /api/statements/{id}`).
- Tests (section 5).

**Out of scope**

- The routes that create or change a statement's state: BE-03 (upload and
  extraction, which sets `processing`, then `ready` or `failed`) and BE-08
  (retry, `failed` back to `processing`). This item only provides the function
  and the vocabulary they use.
- The fields in the list (`GET /api/statements`): BE-06. Its spec is not
  written yet; it must return `status`, `failure_code` and `failure_message`
  with the same names (section 6, question 5).
- The wording of the status labels ("Classificando", "Concluída", "Falhou:")
  and the "Tentar de novo" action: FE-04 and FE-05. The API returns the reason
  only; the frontend adds the "Falhou: " prefix.
- Storing the uploaded PDF or its failure details: BE-04. The failure is a
  code, never an exception message or a text from the PDF.
- Card name and last digits: BE-09.
- Labels of the categories: BE-16.

## 3. Design

### 3.1 The states

`statements.status` is one of three values:

| `status` | Meaning | Set by |
|---|---|---|
| `processing` | The PDF was received and is being classified. No transactions yet | BE-03 (upload), BE-08 (retry) |
| `ready` | The import succeeded. The transactions exist and the board can open | BE-05 import (through the model default) and the success path of BE-03 |
| `failed` | The extraction or the import did not succeed. `failure_code` says why | BE-03, BE-08 |

The database does not enforce the order of the states. It enforces the
consistency of each row (3.2). The order (`processing` to `ready` or `failed`,
and `failed` back to `processing` only by BE-08) is the caller's rule.

### 3.2 The columns and the checks

| Column | Type | Rules |
|---|---|---|
| `status` | `text` | Not null. Default `'ready'` in the table, so that existing rows and an import without a status are ready (section 6, question 3). Check `ck_statements_status_known`: `status in ('processing', 'ready', 'failed')` |
| `failure_code` | `text` | Null. Check `ck_statements_failure_code_known`: `failure_code is null or failure_code in (<the codes of 3.4>)`. The codes are a fixed vocabulary, never free text |
| (table) | | Check `ck_statements_failure_consistent`: `(status = 'failed') = (failure_code is not null)`. A failed statement has a code; any other statement has none |

The default of `status` is set by the migration for existing rows and is kept
on the column. The ORM model also sets `default="ready"`, so a `Statement`
built by BE-05 has the state before the flush.

No index. The list (BE-06) reads the statements of one user through the index
of BE-28, and the state is one column of a few rows per user.

### 3.3 The read (BE-10)

`GET /api/statements/{statement_id}` (BE-10, spec 3.2) gains three fields in
the header. Nothing else in its response changes, and it stays `200` for every
state:

```json
{
  "id": "6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c10",
  "name": "Fatura Cartão Exemplo, jun/2026",
  "status": "failed",
  "failure_code": "invalid_pdf",
  "failure_message": "PDF ilegível",
  "total": null,
  "created_at": "2026-11-10T14:03:00Z",
  "transaction_count": 0,
  "doubtful_count": 0,
  "pending_review_count": 0,
  "transactions": []
}
```

- `status` is the stored value. For a ready statement it is `"ready"`.
- `failure_code` is the stored code, or `null`.
- `failure_message` is the pt-BR reason mapped from the code (3.4), or `null`
  when there is no code. The mapping is done in the API, so the frontend shows
  the text as it is.
- A statement that is not ready (`processing` or `failed`) has no transactions
  and usually no total (section 6, question 4). It is still `200`, not an error.

### 3.4 The vocabulary and its messages

Defined in `server/statements.py`, next to the other refusals:

```python
STATUSES = ("processing", "ready", "failed")
FAILURE_MESSAGES = {  # code -> pt-BR reason, as FE-04 shows it after "Falhou: "
    "invalid_pdf": "PDF ilegível",
    "extraction_unavailable": "o serviço de leitura está indisponível",
    "extraction_timeout": "a leitura demorou demais",
    "extraction_refused": "a leitura da fatura foi recusada",
    "extraction_truncated": "a leitura da fatura ficou incompleta",
    "extraction_invalid": "não foi possível ler a fatura",
    "unknown_category": "há uma categoria desconhecida na fatura",
    "total_mismatch": "a soma dos lançamentos não confere com o total",
    "interrupted": "a leitura foi interrompida",
    "upload_not_available": "o arquivo enviado não está mais disponível",
    "unknown": "erro inesperado",
}
FAILURE_CODES = tuple(FAILURE_MESSAGES)
```

| `failure_code` | Meaning for BE-03 and BE-08 | `failure_message` |
|---|---|---|
| `invalid_pdf` | The file is not a readable PDF, or the magic-bytes check fails | `PDF ilegível` (the text of FE-04 and FE-05) |
| `extraction_unavailable` | No extraction client or key, or the service refused to answer (BE-03) | `o serviço de leitura está indisponível` |
| `extraction_timeout` | The extraction did not finish in its time limit (BE-03) | `a leitura demorou demais` |
| `extraction_refused` | The model refused the document (BE-03) | `a leitura da fatura foi recusada` |
| `extraction_truncated` | The answer was cut off (BE-03) | `a leitura da fatura ficou incompleta` |
| `extraction_invalid` | The answer is not the schema (BE-03) | `não foi possível ler a fatura` |
| `unknown_category` | A line names a category that does not exist (BE-05's refusal) | `há uma categoria desconhecida na fatura` |
| `interrupted` | The process stopped during an extraction, or the blob was missing (BE-03) | `a leitura foi interrompida` |
| `upload_not_available` | A retry found no stored PDF (BE-08) | `o arquivo enviado não está mais disponível` |
| `total_mismatch` | The sum of the extracted lines differs from the printed total (the code of BE-05's refusal) | `a soma dos lançamentos não confere com o total` |
| `unknown` | Anything else. The details go to the log by class name only (BE-03) | `erro inesperado` |

The vocabulary is also written, as literal SQL, in migration `0008`. Adding a
code later is a new migration that changes the check and the dictionary
together. Section 5 has the test that keeps the two equal.

### 3.5 The internal function `set_status`

```python
def set_status(
    session: Session,
    statement_id: UUID,
    status: str,
    failure_code: str | None = None,
    *,
    expected: str | None = None,
    commit: bool = True,
) -> bool:
```

- It is internal. It is not owner-scoped: the caller (BE-03 or BE-08) holds
  the id of the statement it created or is retrying. No route calls it, and
  no route in this item writes the state.
- It checks its arguments before it touches the database and raises `ValueError`
  when `status` is not in `STATUSES`, when `failure_code` is given and
  `status` is not `failed`, when `status` is `failed` and `failure_code` is
  missing, or when `failure_code` is not in `FAILURE_CODES`. The refusal names
  the argument, never the value.
- It is one `UPDATE portal.statements SET status, failure_code (None for every
  state but failed), updated_at = now() WHERE id = :id [AND status = :expected]`.
  It returns `True` when a row was updated and `False` when none matched (a
  missing id, or a status other than `expected`). `expected` is the
  compare-and-set BE-08 needs for the retry claim: two concurrent retries cannot
  both win. With `expected=None` it matches by id alone. Amended 2026-11-21, so BE-03
  and BE-08 can call it as they do.
- `commit=True` (default) commits its own transaction, as `import_statement`
  does. BE-03 passes `commit=False` to put the status change in the same
  transaction as the lines and the blob wipe. It logs nothing.
- It does not change the transactions. A move from `failed` to `processing`
  (BE-08) keeps the statement's id and its lines.

### 3.6 Errors

BE-10's errors do not change: `401` and `403` from BE-23 and BE-24, `404
statement_not_found` (the same answer for unknown, malformed and another user's
ids), and `503 database_unavailable`. `set_status` is not an HTTP route, so it
has no error response of its own.

### 3.7 Logging

Nothing new is logged. The request log (BE-21) records the route template as
before. `set_status` writes no line, so no status or code reaches a log from
this item. BE-03 decides what it logs when it fails.

### 3.8 Migration `0008_statement_status`

File `app/api/migrations/versions/0008_statement_status.py`, `down_revision`
is the head at merge time, which must be `0007` (section 6, question 1).

Upgrade, in one transaction:

1. `op.add_column("statements", sa.Column("status", sa.Text(),
   server_default=sa.text("'ready'"), nullable=False), schema="portal")`. The
   server default fills every existing row with `ready`.
2. `op.add_column("statements", sa.Column("failure_code", sa.Text(),
   nullable=True), schema="portal")`.
3. The three checks of 3.2, with `op.create_check_constraint(op.f(...), ...)`,
   with the vocabularies written as literal SQL text.

Downgrade: drop the three checks (`op.drop_constraint(..., type_="check")`),
then drop the two columns. The downgrade loses the states of the rows; it runs
only on the local database (BE-31, 3.4).

No grant, no policy: the table and its RLS are unchanged, and the default
privileges of `0001` already cover the new columns (section 8, claim 4).

### 3.9 The model

In `server/db/models.py`, the `Statement` class gets two columns and three
checks:

```python
status: Mapped[str] = mapped_column(
    Text, default="ready", server_default=text("'ready'")
)
failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
```

with `CheckConstraint` entries named `status_known`, `failure_code_known` and
`failure_consistent`, so the naming convention produces the names of 3.2.

### 3.10 Steps

One step, about 420 lines with the tests. Branch `feat/be-07-statement-status`,
from `origin/main`, PR to `main`. If the code passes 500 lines, the split is
the migration and the model (step 1) and then the function, the view and their
tests (step 2).

### 3.11 Files

| File | Change |
|---|---|
| `app/api/migrations/versions/0008_statement_status.py` | New: columns, checks, downgrade |
| `app/api/server/db/models.py` | `Statement` gets `status`, `failure_code` and the three checks |
| `app/api/server/statements.py` | `STATUSES`, `FAILURE_MESSAGES`, `FAILURE_CODES`, `set_status`, and `status`, `failure_code`, `failure_message` in `StatementView`; `read_statement` fills them |
| `app/api/tests/test_statement_read.py` | `seeded()` sets `status="ready"` and `failure_code=None` on the `Statement` it builds, since the view now requires `status` |
| `app/api/tests/test_statement_status.py` | New: sections 5.1 and 5.2, no database |
| `app/api/tests/test_statement_status_db.py` | New: section 5.3, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-07 to In progress, then the PR link. Not changed by this spec |

`test_statement_read_db.py` (BE-10) and `test_access_routes.py` need no change
unless one of their assertions compares the whole response dictionary; if one
does, it gets the three new keys.

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge* list for the code; the production step is in section
4.2.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

### 4.1 Merge checks

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-28 and the numbering are in place | `cd app/api && grep -c 'class Statement' server/db/models.py` prints `1`, and `ls app/api/migrations/versions/ \| grep -c '^000[67]_'` prints `2` |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make db-upgrade && make test-db` | All pass, including `test_statement_status_db.py` and the drift test |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_status.py -v` | All pass: `test_status_and_codes_are_fixed`, `test_every_failure_code_has_a_pt_br_message`, `test_migration_vocabulary_matches_code`, `test_set_status_refuses_unknown_status`, `test_set_status_refuses_inconsistent_failure`, `test_get_shows_status_and_failure_message`, `test_processing_statement_has_no_total_and_no_lines`, `test_ready_statement_has_no_failure_message`, `test_no_route_writes_status` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_status_db.py -v` | All pass: `test_status_columns`, `test_existing_statements_become_ready`, `test_check_refuses_unknown_status`, `test_check_refuses_failed_without_code`, `test_check_refuses_code_without_failed`, `test_check_refuses_unknown_failure_code`, `test_set_status_round_trip`, `test_app_role_sets_status`, `test_downgrade_removes_the_columns` |
| 5 | `cd app && make db-current` | `0008 (head)` |
| 6 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select column_name\|\|':'\|\|data_type\|\|':'\|\|is_nullable from information_schema.columns where table_schema='portal' and table_name='statements' and column_name in ('status','failure_code') order by column_name"` | Two lines: `failure_code:text:YES` and `status:text:NO` |
| 7 | `psql ... -Atc "select conname from pg_constraint where conrelid='portal.statements'::regclass and contype='c' order by conname"` | Four lines: `ck_statements_failure_code_known`, `ck_statements_failure_consistent`, `ck_statements_name_not_empty`, `ck_statements_status_known` |
| 8 | `make db-downgrade`, then the query of check 6, then `make db-upgrade` | Empty output, then `0008 (head)` again |
| 9 | `cd app && make test-api`, with a statement from the canonical fixture imported through `import_statement` and read through the route | `GET` returns `"status": "ready"`, `"failure_code": null`, `"failure_message": null`, `"transaction_count": 17` (covered by `test_get_shows_status_and_failure_message` and the BE-10 test of the fixture) |

### 4.2 After merge (deploy)

The owner runs these from `main`, after the merge. The agent does not hold the
production credential and does not connect to Supabase. Migration `0008`
depends on `0006` and `0007` having been applied (section 6, question 1), so
the command is written with `FROM=0007`. The new code must not be deployed
before `0008` is applied, because the read selects the new columns. The
migration is backward compatible, so the old code keeps working until then.

1. `scripts/db-backup.sh` (the owner's backup, as BE-28, 3.5).
2. `make db-sql FROM=0007` and read the SQL. It adds two columns to
   `portal.statements`, adds three checks and nothing else: no password, no
   data, nothing outside `portal`. The owner answers "apply".
3. `make db-upgrade && make db-current` against Supabase: `0008 (head)`.
4. `psql "$PORTAL_MIGRATION_DATABASE_URL" -Atc "select status, count(*) from portal.statements group by status"`:
   `ready|N` for every existing row, or no output when the table is empty.
   Recorded as "validated on <date>", with no count in the repository.

## 5. Tests

Fictitious data only: the canonical fixture, imported through `import_statement`
(BE-05), and rows built in memory with obviously fictitious names
("Fatura Cartão Exemplo, jun/2026", "PDF ilegível" is the text of FE-04). Access
and the user row use `tests/access_helpers.py` and the BE-24 pattern, with the
verifier faked. No call leaves the machine.

### 5.1 `test_statement_status.py` (no database)

Which app each test uses is stated in the table. The session of the
no-database tests is the `FakeSession` of `test_statement_read.py`, or a session
that fails on any use.

| Test | App | Asserts |
|---|---|---|
| `test_status_and_codes_are_fixed` | Pure | `STATUSES == ("processing", "ready", "failed")`; `FAILURE_CODES` is the eleven codes of 3.4, in that order |
| `test_every_failure_code_has_a_pt_br_message` | Pure | Every code has a non-empty `FAILURE_MESSAGES` entry, and `invalid_pdf` maps to `"PDF ilegível"` |
| `test_migration_vocabulary_matches_code` | Pure | The module `migrations/versions/0008_statement_status.py`, loaded by `importlib.util.spec_from_file_location`, holds the same status values and failure codes as `server.statements` (its checks are read from its module-level constants) |
| `test_set_status_refuses_unknown_status` | Pure, session fails on use | `set_status(..., "archived")` raises `ValueError`, names the argument and not the value, and the session is never used |
| `test_set_status_refuses_inconsistent_failure` | Pure, session fails on use | `failed` with no code, `ready` with a code, and an unknown code each raise `ValueError` before the session is used |
| `test_get_shows_status_and_failure_message` | Overrides: `get_session` a `FakeSession` with a `failed` statement, `current_user` a `User` | `200`; `status` `"failed"`, `failure_code` `"invalid_pdf"`, `failure_message` `"PDF ilegível"`, `transactions` `[]` |
| `test_processing_statement_has_no_total_and_no_lines` | Overrides, as above, a `processing` statement with `total_lanc_atuais=None` | `200`; `status` `"processing"`, `total` `null`, `transaction_count` 0, `failure_message` `null` |
| `test_ready_statement_has_no_failure_message` | Overrides, a `ready` statement with one line | `status` `"ready"`, `failure_code` `null`, `failure_message` `null` |
| `test_no_route_writes_status` | Plain `create_app` | The routes under `/api/statements` have exactly these method and path pairs: `POST /api/statements`, `GET /api/statements/{statement_id}`, `PATCH /api/statements/{statement_id}/transactions/{transaction_id}`, `GET /api/statements/{statement_id}/summary`. Any other write route fails the test |

### 5.2 Changes to the BE-10 tests (`test_statement_read.py`)

`seeded()` builds the `Statement` with `status="ready"` and `failure_code=None`.
Its existing tests keep their assertions. No new test is needed there: section
5.1 covers the new fields.

### 5.3 `test_statement_status_db.py` (marker `db`, local Postgres, as `app_backend` where stated)

| Test | Asserts |
|---|---|
| `test_status_columns` | `status` is `text` not null, and `failure_code` is `text` null, as in check 6 of section 4.1 |
| `test_existing_statements_become_ready` | Migrate to `0007` with `alembic.command.upgrade`, insert a user and a statement with plain SQL (`user_id`, `name`, no status), then `upgrade head`: the row has `status` `ready` and `failure_code` null |
| `test_check_refuses_unknown_status` | An insert with `status` `'archived'` raises `IntegrityError` on `ck_statements_status_known` |
| `test_check_refuses_failed_without_code` | `status` `'failed'` with a null code raises `IntegrityError` on `ck_statements_failure_consistent` |
| `test_check_refuses_code_without_failed` | `status` `'ready'` with `failure_code` `'timeout'` raises `IntegrityError` on `ck_statements_failure_consistent` |
| `test_check_refuses_unknown_failure_code` | `status` `'failed'` with `failure_code` `'stack trace'` raises `IntegrityError` on `ck_statements_failure_code_known` |
| `test_set_status_round_trip` | `set_status` to `processing`, then `failed` with `timeout`, then `ready`: each step reads back, `failure_code` is null at the end, and `updated_at` moves |
| `test_app_role_sets_status` | As `app_backend`, `set_status` on its own statement works, with no `GRANT` added by this item |
| `test_downgrade_removes_the_columns` | `downgrade 0007` removes `status` and `failure_code`, and `upgrade head` brings them back with every existing row `ready` |

The drift test of BE-31 (`test_models_match_migrations`, in `test_migrations_db.py`)
already covers the two columns: it runs in check 2 and must report no
difference.

## 6. Open questions

Each question has a recommendation. The owner is away: each recommendation is
adopted, as marked.

1. **Migration number and order.** `test_revision_ids_are_sequential` requires
   the files `0001` to `0008` to exist, so `0008` cannot be merged while `0006`
   (BE-13) and `0007` (BE-09) are missing. *Recommended: BE-07 is implemented
   after BE-13 and BE-09 are merged, and its Depends on lists them for the
   numbering. The item keeps its number and its `down_revision` is `0007`.
   The alternative is to renumber this item, which the backlog's rule that IDs
   and numbers are never reused makes awkward, or to relax the sequence test,
   which weakens a guard.* (delegated: the owner is away; the recommendation will
   be adopted)

2. **The failure vocabulary and its wording.** *Recommended: the eleven codes of
   3.4, with the messages there. `invalid_pdf` is "PDF ilegível", the text of
   FE-04 and FE-05. The other messages are written to read after "Falhou: "
   (lower case, as in "Falhou: erro inesperado"). The owner can change a message
   without a migration, since only the codes are checked in SQL.* (delegated:
   the owner is away; the recommendation will be adopted)

3. **The default of `status`.** *Recommended: keep `default 'ready'` on the
   column and on the model. Existing rows are ready, and BE-05's import creates
   ready statements without naming a state. BE-03 must set `processing` on
   purpose, and its spec will say so and test it. The alternative is no default,
   which makes BE-05 set `ready` itself and makes a forgotten state fail loudly.*
   (delegated: the owner is away; the recommendation will be adopted)

4. **Transactions and totals of a statement that is not ready.** *Recommended:
   still readable, and empty. BE-10 returns `200` with `status` and
   `failure_message`, `transactions` `[]` and `total` `null`, which the model
   already allows (BE-28). BE-11's PATCH returns `404 transaction_not_found`,
   because there is no line to change. BE-12 returns its ten categories with
   zero totals and `share` `null`, and no error. Nothing returns `409` for a
   state; the board shows the state instead.* (delegated: the owner is away; the
   recommendation will be adopted)

5. **The list (BE-06) and its fields.** *Recommended: BE-06's item list returns
   `status`, `failure_code` and `failure_message` with the same names and
   meanings as BE-10, and BE-06's spec lists BE-07 in its Depends on. BE-06 is
   still a draft, so this is recorded here, not built here.* (delegated: the
   owner is away; the recommendation will be adopted)

6. **Where the pt-BR mapping lives.** *Recommended: in the API, in
   `FAILURE_MESSAGES`, returned as `failure_message`. The frontend shows it and
   adds the "Falhou: " prefix. The labels of the states ("Classificando",
   "Concluída") stay in the frontend, because FE-04 owns them and they are not
   errors. BE-16 decides only the category labels.* (delegated: the owner is
   away; the recommendation will be adopted)

7. **Whether `set_status` commits and whether it checks the order of the
   states.** *Recommended: it commits, as `import_statement` does, and it checks
   only the values and their consistency (3.5), not the order. The order is
   BE-03's and BE-08's rule, and their specs test it. The alternative is a
   transition table in this function, which couples three specs to one
   function.* (delegated: the owner is away; the recommendation will be adopted)

### Gaps for the owner

These are gaps between the backlog and this spec. The spec does not change the
backlog; the owner decides.

- **BE-07's Depends on** says BE-28 only. It should also list BE-10 (its
  response changes) and BE-13 and BE-09 (the migration numbers, question 1).
- **BE-06** (`GET /api/statements`) is a draft with no spec. Its spec must
  return the three fields of question 5, and list BE-07 in its Depends on.
- **BE-03** and **BE-08** are drafts. Their specs must call `set_status` with
  the codes of 3.4, and must not add a code without a migration that changes
  the check (question 2).
- **FE-04** shows "Falhou: <reason>" from `failure_message`. Its wording of the
  reasons, and the capital letter after "Falhou: ", is the story's decision.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-28 merged: the `Statement` model exists | Agent | `cd app/api && grep -c 'class Statement' server/db/models.py` | `1` |
| BE-13 and BE-09 merged, so `0006` and `0007` exist (question 1) | Agent | `cd app/api && ls migrations/versions/ \| grep -c '^000[67]_'` | `2` |
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| Local Postgres at the head before this item | Agent | `cd app && make db-up && make db-current` | `0007 (head)` |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted (delegated, 2026-11-21) |
| `pg_dump` and `psql` on the owner's machine, for the production step | Owner | `pg_dump --version && psql --version` | `pg_dump` 17 or newer |
| Supabase has `0007` applied, before the production step | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-current` | `0007 (head)` |

**Packages.** None.

**Actions that need the owner's explicit OK.** Applying `0008` to Supabase
(section 4.2): the owner reads `make db-sql FROM=0007` and says "apply". The
agent never holds a production credential and never connects to Supabase.

**Cost.** None. A failed migration leaves nothing behind, because it runs in a
transaction.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | Existing rows satisfy the three checks once `status` is backfilled `ready` and `failure_code` is null | *Verified* by reading the checks: a row with `ready` and no code is consistent | `test_existing_statements_become_ready` |
| 2 | The naming convention turns `op.f("ck_statements_status_known")` and the model's `CheckConstraint("...", name="status_known")` into the same name | *Verified* by the existing `ck_statements_name_not_empty` in `0004` and `models.py` | Check 7 |
| 3 | Alembic's drift comparison does not report the check constraints, so the model and the migration may differ in their text | *Assumed* | `test_models_match_migrations` runs in check 2; if it reports a check, the model text is made equal to the migration's |
| 4 | The default privileges of `0001` cover the two new columns: `app_backend` reads and writes them with no `GRANT` | *Verified* for the table (`0004`, `test_app_role_reads_and_writes_statements` in BE-28); *assumed* for columns added later | `test_app_role_sets_status` |
| 5 | `Mapped[str]` with `default="ready"` gives the ORM object its state before the flush, and `server_default` gives it to the table | *Assumed* from SQLAlchemy 2.0 behaviour | `test_get_shows_status_and_failure_message` builds the object with its state; `test_status_columns` reads the table |
| 6 | `app.routes` lists each route with its `methods` and `path`, which `test_no_route_writes_status` reads | *Assumed* | First run of the test |
| 7 | A migration file whose name starts with a digit loads with `importlib.util.spec_from_file_location` | *Assumed* | `test_migration_vocabulary_matches_code` |
| 8 | `command.upgrade(config, "0007")` works with the revision ids of the file names, as `test_migrations_db.py` uses `"head"` | *Assumed* | `test_existing_statements_become_ready` |

## 9. Notes for the implementer

- `failure_code` and `status` are the only two states that the database checks.
  `failure_message` is computed in Python and is never stored, so a change to
  the wording needs no migration.
- `set_status` is the only writer. Do not add a second writer, and do not give
  it a route: the owner-scoped routes of BE-10 and BE-11 never need it.
- `read_statement` reads `status` and `failure_code` from the row it already
  loads. It adds no query.
