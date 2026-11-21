# Spec — BE-13 Record whether a transaction's category was changed by the user

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-13 |
| **Story** | FE-08 ("Movido por você" on a card, in the lane view). FE-09 and FE-12 also show "Movido por você" in their scenarios, see section 6, gap 1 |
| **Prototype** | `docs/prototypes/portal/v3.html#board` |
| **Depends on** | BE-11 (Done, #92 and #93). BE-05 and BE-10 (Done) |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

The board marks a card "Movido por você" when the person has moved it to another
category. The server must say so: the browser cannot tell a move from the
extraction's category, because it only sees the current one. This item stores the
category the extraction gave each line (`original_category_code`), and adds
`moved_by_user` to every transaction the API returns: `true` when the current
category differs from the original. It is read in BE-10's `GET` and in BE-11's
`PATCH`, so the card is right after a drag, with no extra request.

## 2. Scope

**In scope**

- Migration `0006`: the column `portal.transactions.original_category_code`,
  backfilled, `NOT NULL`, with a foreign key to `portal.categories.code`, and its
  downgrade.
- The ORM model `Transaction` gets the column.
- The import (`import_statement`, BE-05) stores the original category of each line.
- `TransactionView` gets `moved_by_user` (bool). BE-10's `GET` and BE-11's `PATCH`
  return it.
- Tests (section 5), and the test updates that the new field needs in BE-10 and
  BE-11.

**Out of scope**

- Showing the original category ("Era: Operacional"). The API does not return
  `original_category_code`; only the flag. A later item if the board needs it.
- Any change to what `PATCH` writes. BE-11 still writes only `category_code` and
  `reviewed`; the original is never written after the import.
- A per-line history of moves, or who moved a line. Not in any story.
- The lane and card rendering: FE-08, FE-09, FE-12.
- Labels for categories: BE-16.

## 3. Design

### 3.1 The migration (`0006`, owner-run)

File `app/api/migrations/versions/0006_transaction_original_category.py`,
`revision = "0006"`, `down_revision = "0005"`. The steps, in one transaction (each
migration runs in its own transaction, `docs/deploy/supabase.md`, section 3):

1. Add `original_category_code` as `Text`, nullable.
2. Backfill: `UPDATE portal.transactions SET original_category_code = category_code
   WHERE original_category_code IS NULL`. The extraction's category is not stored
   anywhere else, so for a line that already exists the current category is the
   best value there is (section 6, question 1).
3. Set the column `NOT NULL`.
4. Add the foreign key `fk_transactions_original_category_code_categories`
   (`original_category_code` to `portal.categories.code`), `ON DELETE RESTRICT`,
   as `category_code` has it (BE-29). The name follows `NAMING_CONVENTION` in
   `server/db/base.py`.

No `server_default`. The import always sets the value, and a missing value must
fail, not default silently.

**Grants.** None to add. The baseline's default privileges give `app_backend`
`SELECT, INSERT, UPDATE, DELETE` on every table of `portal` (`0001_baseline.py`,
lines 46 to 49), which covers a new column. `0003` revoked writes on
`portal.categories` only. The RLS policy `backend_only` is on the table, so the
new column needs nothing (`migrations/helpers.py`).

**Downgrade.** Drop the foreign key, then the column. `make db-downgrade` runs only
against the local Postgres (`migrations/guards.py`), so a production downgrade is
refused and production moves forward only.

**Deploy order and the window.** The column is `NOT NULL`, so an import by the
code that is currently deployed (BE-05, which does not set the column) fails from
the moment the migration runs until the new code is deployed. Reads by the
current code are not affected, because the old model does not select the column.
The owner runs the migration and the deploy back to back (section 4, after-merge
list). This is the one place where the migration is not backward compatible for
writes. It is recorded in section 6, question 2.

### 3.2 The model and the import

- `server/db/models.py`, `Transaction`: `original_category_code: Mapped[str] =
  mapped_column(ForeignKey("categories.code", ondelete="RESTRICT"))`, the same
  shape as `category_code`.
- `server/statements.py`, `import_statement`: the row dict of the `insert(Transaction)`
  gets `"original_category_code": line.categoria`. The line's category has already
  been checked against the table (rule 8), so the foreign key holds. The import
  is the only place that writes the original.
- `update_transaction` (BE-11) does not change. It writes only the fields the
  request sends, and never the original.

### 3.3 The flag in the responses

`TransactionView` (BE-10, `server/statements.py`) gets one field:

```json
{"id": "...", "item_number": 8, "section": "purchases", "printed_date": "...",
 "description": "Notebook Loja Fictícia", "amount": "4899.00",
 "category_code": "FORNECEDOR", "doubtful": false, "reviewed": false,
 "moved_by_user": true}
```

- `moved_by_user` is `category_code != original_category_code`, computed in
  `transaction_view(item)`. It is derived, not stored, so it can never disagree
  with the two values it compares. A move and its undo give `true` and then `false`
  with no extra write.
- It is a JSON boolean, always present, in every `transactions[]` element of
  BE-10 and in the body of BE-11's `200`.
- `original_category_code` is not returned (section 2).
- Counts, `pending_review_count` and the summary of BE-12 do not change. A moved
  line keeps its `doubtful` and `reviewed`.

**Changes to approved specs.** This is an additive field in two approved
responses, so it needs the owner's approval, like BE-11's change to BE-10 (BE-11,
section 3.6). The same change is recorded here and in BE-10's and BE-11's test
lists: BE-10 section 3.2 and BE-11 section 3.2 each gain `moved_by_user`, after
the owner approves this spec.

### 3.4 Errors and logging

No new errors and no new log lines. The request log (BE-21) is unchanged. No
category text and no line value is logged.

### 3.5 Steps

One step, estimated at about 300 to 350 lines with the tests. Branch
`feat/be-13-moved-by-user`, from `origin/main`, PR to `main`. No size exception is
needed.

### 3.6 Files

| File | Change |
|---|---|
| `app/api/migrations/versions/0006_transaction_original_category.py` | New: section 3.1, with `downgrade` |
| `app/api/server/db/models.py` | `Transaction.original_category_code` (3.2) |
| `app/api/server/statements.py` | `TransactionView.moved_by_user`, set in `transaction_view`; `import_statement` sets `original_category_code` (3.2, 3.3) |
| `app/api/server/routes/statements.py` | No change |
| `app/api/tests/test_migration_0006_db.py` | New: section 5.1, marker `db` |
| `app/api/tests/test_transaction_moved.py` | New: section 5.2, no database |
| `app/api/tests/test_transaction_moved_db.py` | New: section 5.3, marker `db` |
| BE-10 and BE-11 tests that compare a whole transaction object | Add `moved_by_user` to the expected object. Found by searching for the transaction keys at implementation (section 8, claim 7) |
| `docs/specs/categorizer/BE-10-get-statement.md`, `BE-11-update-transaction.md` | Section 3.2 gets `moved_by_user`, after the owner approves 3.3 |
| `docs/BACKLOG.md` | At implementation: BE-13 to In progress, then the PR link. Not changed by this spec |

The drift test (`test_models_match_migrations`) and the RLS invariant
(`test_rls_invariant_holds`) run unchanged and must pass with the new migration.

## 4. Verification

Checks 0 to 7 run when the item merges, with the local Postgres (`make db-up`).
The after-merge list runs on production, after the owner has read the SQL.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-11 is merged | `cd app/api && grep -n '@router.patch' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including the drift test, the RLS invariant and `test_migration_0006_db.py` |
| 3 | `cd app && make db-upgrade && make db-current` (local) | `0006 (head)` |
| 4 | `cd app && make db-downgrade && make db-current` (local) | `0005`, and then `cd app && make db-upgrade` returns to `0006 (head)` |
| 5 | `cd app/api && .venv/bin/python -m pytest tests/test_transaction_moved.py -v` | All pass: `test_moved_by_user_compares_the_two_categories`, `test_moved_by_user_is_always_a_bool` |
| 6 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_migration_0006_db.py tests/test_transaction_moved_db.py -v` | All pass (section 5.1 and 5.3) |
| 7 | The fixture's flags: after the import of the canonical fixture, `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.transactions where category_code <> original_category_code;"` | `0` (the import sets both to the same category) |

### After merge (deploy)

The owner runs these from `main`, with the owner URL of `docs/deploy/supabase.md`,
section 1. The agent does not hold the credential.

1. **Plan.** `cd app && make db-sql FROM=0005`. Read the SQL: the `ADD COLUMN`,
   the `UPDATE`, the `SET NOT NULL`, the `ADD CONSTRAINT`. Approve only that SQL.
2. **Backup.** Section 3 of `docs/deploy/supabase.md`, step 2 (`pg_dump` or
   `scripts/db-backup.sh`).
3. **Apply and deploy back to back.** `cd app && make db-upgrade && make db-current`
   must print `0006 (head)`. Then deploy the tag that contains this PR
   (`/opt/odiservices/app/deploy/deploy.sh <tag>`), so the code that sets the
   column is running before any import.
4. **Backfill check** (as the owner, in `psql`): `select count(*) from portal.transactions where original_category_code is null;` must print `0`.
5. **Flag check.** `GET /api/statements/{id}` of an existing statement, through
   the portal in the browser, shows `"moved_by_user": false` on every line. A line
   that the owner moved before this deploy also shows `false` (section 6, question 1).

## 5. Tests

Fictitious data only: the canonical fixture (`app/fixtures/statement-example-2026-09.json`),
imported through `import_statement` (BE-05). The line used for moves is line 8,
"Notebook Loja Fictícia", 4899.00 in `INVESTIMENTO`, as in BE-12's tests. Access and
the user row use `tests/access_helpers.py` and the BE-24 pattern, with the verifier
faked. No call leaves the machine.

### 5.1 `test_migration_0006_db.py` (marker `db`, local Postgres, owner role)

Uses the `database` fixture of `test_migrations_db.py` (a throwaway database).

| Test | Asserts |
|---|---|
| `test_backfill_copies_the_current_category` | Migrate to `0005`, insert a user, a statement and two lines with SQL, migrate to `head`: both lines have `original_category_code` equal to `category_code` |
| `test_column_is_not_null` | An insert without the column fails with `NotNullViolation` |
| `test_original_must_be_a_known_category` | An `original_category_code` of `NAO EXISTE` fails with the foreign key error |
| `test_downgrade_removes_the_column` | Downgrade to `0005`: the column is gone, the rows keep their `category_code` |
| `test_app_backend_reads_and_updates_the_column` | As `app_backend`, `select original_category_code` and an `UPDATE` of it both succeed |

### 5.2 `test_transaction_moved.py` (no database)

| Test | Asserts |
|---|---|
| `test_moved_by_user_compares_the_two_categories` | `transaction_view` of a `Transaction`-like object with `category_code` `OPERACIONAL` and `original_category_code` `FORNECEDOR` gives `moved_by_user` true; with equal codes, false |
| `test_moved_by_user_is_always_a_bool` | The key is present and is `True` or `False`, never `None`, in the dumped model |

### 5.3 `test_transaction_moved_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_import_sets_original_to_the_imported_category` | After the import of the fixture, every row has `original_category_code` equal to `category_code`; the `GET` shows `moved_by_user` false on all 17 lines |
| `test_move_sets_the_flag` | `PATCH` of line 8 to `FORNECEDOR` gives `200` with `moved_by_user` true; the database row keeps `original_category_code` `INVESTIMENTO` |
| `test_move_back_clears_the_flag` | `PATCH` of line 8 back to `INVESTIMENTO`: `moved_by_user` false, `original_category_code` still `INVESTIMENTO` |
| `test_confirm_does_not_set_the_flag` | `PATCH` `{"reviewed": true}` on a doubtful line: `moved_by_user` stays false |
| `test_read_marks_only_the_moved_line` | After the move, `GET /api/statements/{id}` has `moved_by_user` true on line 8 and false on the other 16 |
| `test_move_then_undo_restores_the_import_state` | Move, then the previous category: the row equals its state after the import, including `moved_by_user` false |

## 6. Open questions

Each question has a recommendation. The owner is away, so these are delegated:
the recommendations will be adopted unless the owner says otherwise.

1. **Moves made before `0006`.** There is no history of the original category, so
   the backfill sets it to the current category. A line moved on the board before
   this migration will show `moved_by_user` false. *Recommended: accept this, and
   say it in section 4, after-merge step 5. The alternative is to keep the flag
   nullable and show nothing for old rows, which hides the same fact.
   (delegated: the owner is away; the recommendation will be adopted)*
2. **The window between the migration and the deploy.** With `NOT NULL`, an import
   by the old code fails from the migration until the new code runs (3.1). *Recommended:
   accept, run the migration and the deploy back to back (after-merge step 3). The
   only importer today is the owner's `POST /api/statements` (BE-05). The alternative
   is a nullable column with a trigger that copies `category_code` on insert, which
   keeps the old code working but adds a trigger that the drift test does not see.
   (delegated: the owner is away; the recommendation will be adopted)*
3. **Store the flag or derive it.** *Recommended: derive it from the two columns
   (3.3). A stored flag could disagree after an undo or a direct write.
   (delegated: the owner is away; the recommendation will be adopted)*
4. **Expose the original category.** *Recommended: no. Only the flag is returned.
   The original is kept for the flag and for later use; the board does not show it
   in any story. (delegated: the owner is away; the recommendation will be adopted)*
5. **Foreign key action.** *Recommended: `ON DELETE RESTRICT`, as `category_code`
   (BE-29). The categories are not deleted (BE-30). (delegated: the owner is away;
   the recommendation will be adopted)*
6. **Approval of the changes to BE-10 and BE-11** (3.3). *Recommended: approve,
   because the change is additive. (delegated: the owner is away; the recommendation
   will be adopted)*

### Gaps for the owner

- **FE-09 and FE-12** show "Movido por você" in their scenarios, and the backlog
  lists only BE-11 for them. They need BE-13 too. FE-08 already lists BE-13. The
  backlog should list BE-13 for FE-09 and FE-12, as BE-11's spec recorded for
  itself (BE-11, section 2).

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-11 merged: the `PATCH` route exists | Agent | `cd app/api && grep -n '@router.patch' server/routes/statements.py` | One line |
| Migration head is `0005` | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| Categories seeded (10) | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| The owner's approval of section 3.3 and of section 6 | Owner | (none) | Recorded in this spec before implementation |
| Production: the owner reads `make db-sql FROM=0005` and takes a backup before the deploy | Owner | (after merge) | Section 4, after-merge steps 1 and 2 |

**Packages.** None.

**Actions that need the owner's explicit OK.** The approval of the two responses
(3.3). The production migration and deploy (after-merge steps 1 to 3). No
production credential is held by the agent.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `app_backend` reads and writes every table in `portal`, so the new column needs no grant | *Verified*: `0001_baseline.py`, default privileges, lines 46 to 49 | `test_app_backend_reads_and_updates_the_column` |
| 2 | The `backend_only` policy is per table and covers the new column | *Verified*: `migrations/helpers.py` | `test_rls_invariant_holds` (unchanged) |
| 3 | The FK name follows `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` | *Verified*: `server/db/base.py`, `NAMING_CONVENTION` | `test_models_match_migrations` |
| 4 | `SET NOT NULL` after an `UPDATE` in the same migration transaction works on Postgres 17 | *Assumed* | `test_backfill_copies_the_current_category` (the migration runs end to end) |
| 5 | The backfill and `SET NOT NULL` lock the table only briefly on production (a small table) | *Assumed*: the owner's data is one statement at a time, a few thousand rows at most | After-merge step 3; the owner watches the time of the `db-upgrade` |
| 6 | `import_statement` is the only writer of new transactions | *Verified*: `server/statements.py`, `insert(Transaction)` is in `import_statement` only. BE-03 will call the same import (backlog, BE-05 notes) | Test `test_import_sets_original_to_the_imported_category` |
| 7 | BE-10's and BE-11's tests compare the transaction object with exact keys, so they need `moved_by_user` | *Assumed*: not read in this spec | The test run after the change (check 1) shows the failures |
| 8 | `moved_by_user` as a derived value does not need a column index | *Assumed*: the comparison is per line, on at most 500 lines | None needed |

## 9. Notes for the implementer

- `original_category_code` is written only by `import_statement`. Do not add it to
  `TransactionPatch`: the PATCH model is `extra="forbid"`, so a client cannot send it.
- `transaction_view` is shared by BE-10's `read_statement` and BE-11's
  `update_transaction`, so both responses get the flag from one place.
- The migration's `UPDATE` must run before `SET NOT NULL`, in the same revision, in
  that order. Splitting them into two revisions would leave a window where the
  column is nullable and the code assumes it is not.
