# Spec — BE-04 Keep an uploaded PDF only as an encrypted blob, while its statement is not ready

| | |
|---|---|
| **Backlog** | Features: statement upload and processing (backend) › BE-04 |
| **Story** | FE-03 (upload, "Até 10 MB"), FE-05 (retry without a new upload). No story shows the retention itself |
| **Prototype** | None |
| **Depends on** | BE-28 (Done, #81 #82 #84), BE-18 (Done, #13), BE-19 (Done, #14), BE-31 (Done). BE-07 (Draft) must be merged first for one reason only: the migration number and head (section 3.6). BE-07's status concept is not used by this module |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

A card statement PDF is sensitive, and the portal needs it only for the
extraction. The retention rule, decided in `HANDOFF-SPEC-PREAMBLE.md` and
restated here, is: the PDF is never written to disk, and it is kept in the
database only as a Fernet-encrypted blob, and only while its statement is not
`ready`. It is wiped when the extraction succeeds and when the statement is
deleted. A failed statement keeps its blob so that BE-08 "Tentar de novo" can
retry without a new upload.

This item builds the storage: the table `portal.statement_uploads` (migration
0009), the ORM model, the setting for the key, and the module
`server/uploads.py` with `store_upload`, `load_upload` and `wipe_upload`. The
module does not know about statuses. The rule "only while not ready" is kept by
its callers, BE-03 and BE-08 (section 3.2), so this module stays usable and
testable on its own.

## 2. Scope

**In scope**

- Migration `0009`: table `portal.statement_uploads`, RLS like `0004` and `0005`.
- The ORM model `StatementUpload` in `server/db/models.py`, so the drift test passes.
- Setting `PORTAL_UPLOAD_ENCRYPTION_KEY` (optional, `SecretStr`) in `server/settings.py`,
  and its name and comment in `.env.example`.
- `cryptography` as a direct runtime dependency, pinned.
- `server/uploads.py`: the size limit, the seal and open functions, the three
  store, load and wipe functions, and `UploadError`.
- The doc update in `docs/BACKEND_GUIDELINES.md` (section 3.8).
- Tests (section 5).

**Out of scope**

- Any route. The upload route, the extraction and the retry are BE-03 and BE-08.
  This item adds no endpoint and no `status` column (BE-07).
- Deciding when a blob is stored, kept or wiped. That is BE-03 and BE-08 (3.2).
- Key rotation. Out of scope, with a note in section 3.5.
- A time limit (TTL) for failed statements. An owner decision, recorded in section 6.
- Real PDFs. Tests use fictitious bytes (section 5).

## 3. Design

### 3.1 The table

Migration `app/api/migrations/versions/0009_statement_uploads.py`, following
`0004` and `0005`:

- `statement_uploads`, schema `portal`:
  - `statement_id uuid` primary key, foreign key to `portal.statements.id`,
    `ON DELETE CASCADE`. One blob per statement, and BE-15's hard delete removes
    it with the statement.
  - `ciphertext bytea` not null, with `CHECK (octet_length(ciphertext) > 0)`.
    It holds the Fernet token as bytes (base64 text, as Fernet produces it). For a
    10 MiB PDF it is about 13.4 MiB.
  - `created_at timestamptz` not null, default `now()`.
- `enable_backend_only_rls("statement_uploads")`: RLS on, and one policy for
  `app_backend`. Nothing else can read the blob.
- Names follow the `op.f` pattern: `pk_statement_uploads`,
  `fk_statement_uploads_statement_id_statements`,
  `ck_statement_uploads_ciphertext_not_empty`.
- `downgrade()` drops the table.

**Grants.** `0004` and `0005` add no explicit `GRANT`. The default privileges set
in `0001_baseline.py` (lines 45 to 52) give `app_backend` `SELECT, INSERT, UPDATE,
DELETE` on every new table in `portal`. This migration does the same. The drift
test in `tests/test_migrations_db.py` (lines 75 to 98) checks the result with
`has_table_privilege`. Alternative (section 6, question 2): an explicit `GRANT`.

**Reachability.** The table is reachable only through a statement the user
owns. The module takes a `statement_id` and never a user id. The caller checks
ownership first with `owned_statement` (`server/statements.py`, line 297), as
BE-10 does. A caller that passes another user's statement id gets the same
answer as for a missing one (`upload_missing`), with no lookup of the blob. The
blob itself is only ever read by the backend role.

**Migration order.** `0009`'s `down_revision` is the head at merge time. Today it
is `0005`. Migration numbers `0006` (BE-13), `0007` (BE-09) and `0008` (BE-07)
are reserved. `tests/test_migration_files.py::test_revision_ids_are_sequential`
requires consecutive numbers with no gap, so `0009` cannot merge before `0006` to
`0008` exist. This is why BE-07 is in **Depends on** (section 3.6).

### 3.2 What the callers do (the "not ready" rule)

The module does not look at a status. The following rule goes into the specs of
BE-03 and BE-08, and is repeated here so that the three specs agree:

| Moment | Caller | Module call | Rule |
|---|---|---|---|
| Upload accepted | BE-03, one transaction: insert the statement in `processing`, then store, then commit | `store_upload` | The statement row and the blob are created together. If the store fails, no statement is created |
| Extraction succeeds | BE-03, in the same transaction as the BE-05 import and the status `ready` | `wipe_upload` | The blob is gone in the same commit that makes the statement `ready` |
| Extraction fails | BE-03 | none | The status becomes `failed` with a `failure_code`. The blob stays |
| Retry | BE-08 | `load_upload` | Allowed only when the status is `failed` (409 otherwise). A `ready` statement never has its blob read |
| Statement deleted | BE-15 | none | The database removes the blob (`ON DELETE CASCADE`) |
| Blob unreadable on retry | BE-08 | `load_upload` raises `upload_unreadable` | The status stays `failed` with `failure_code` `upload_unreadable`, and the pt-BR reason tells the user to upload again |

**What this item needs from BE-07:**

1. The migration head `0008` exists when this item merges (3.1).
2. The status vocabulary is `processing`, `ready`, `failed`, as the handoff
   decided. This item relies on it only in the table above.
3. The `failure_code` vocabulary includes `upload_unreadable`, `upload_key_missing`
   and `database_unavailable`, for the callers to record. This item adds no code
   to the BE-07 vocabulary itself.

**Attention point for the owner (not a decision of this item).** A `failed`
statement keeps its PDF encrypted until it is retried or deleted, with no time
limit. This is the handoff's decision and is listed in section 6, question 6.

### 3.3 The module: `server/uploads.py`

```python
MAX_PDF_BYTES = 10 * 1024 * 1024  # the "Até 10 MB" of FE-03, shared with BE-03

class UploadError(Exception):
    # code is one of the fixed values below; str(exc) is the code and nothing else
    code: str

# codes: "upload_key_missing", "upload_too_large", "upload_exists",
#        "upload_missing", "upload_unreadable", "database_unavailable"

def seal_pdf(pdf_bytes: bytes, key: str) -> bytes: ...   # Fernet(key).encrypt
def open_pdf(token: bytes, key: str) -> bytes: ...       # Fernet(key).decrypt; InvalidToken -> upload_unreadable

def store_upload(session: Session, statement_id: UUID, pdf_bytes: bytes,
                 *, settings: Settings | None = None) -> None: ...
def load_upload(session: Session, statement_id: UUID,
                *, settings: Settings | None = None) -> bytes: ...
def wipe_upload(session: Session, statement_id: UUID) -> bool: ...
```

Behavior:

- **Order of checks in `store_upload`:** size first (`upload_too_large` when
  `len(pdf_bytes) > MAX_PDF_BYTES`, with no key needed), then the key
  (`upload_key_missing` when the setting is unset), then the seal, then the
  insert.
- **`store_upload`** inserts a row and calls `session.flush()`. It does not
  commit: the caller owns the transaction (3.2). A duplicate statement id is
  `upload_exists`. Database errors are caught as in section 3.5.
- **`load_upload`** selects the row, then opens the token. No row gives
  `upload_missing`. A token that does not open (wrong key, a changed byte or a
  malformed token) gives `upload_unreadable`. The function never returns a
  partial result.
- **`wipe_upload`** deletes the row and returns `True` if one was removed. It is
  idempotent: a second call returns `False` and raises nothing.
- **Database errors** (`DBAPIError` from SQLAlchemy, except `IntegrityError` in
  store, which is `upload_exists`): the module logs the class name only and
  raises `UploadError("database_unavailable")`. The route or caller turns it
  into `AccessError(*DATABASE_UNAVAILABLE)` as `server/statements.py` does
  (`server/db/session.py`). The module does not import `AccessError`.
- **Key:** `settings` defaults to `get_settings()`. Tests pass their own
  `Settings`, so they never read `.env`.
- **Logging:** the module logs nothing on success. On failure it logs the code
  and the class name, never the key, the bytes, the token, the exception message
  of `cryptography` or the SQL. A statement id is allowed in a log line
  (`docs/BACKEND_GUIDELINES.md`, Logging), but this module does not log one.

### 3.4 Settings and `.env.example`

- `server/settings.py`: one field, `upload_encryption_key: SecretStr | None =
  Field(None, alias="PORTAL_UPLOAD_ENCRYPTION_KEY")`. Added to the `blank_is_unset`
  validator, so an empty value in a copied `.env.example` counts as unset.
- A validator checks the format **when the value is set**: `Fernet(value)` must
  accept it, else `ValueError("PORTAL_UPLOAD_ENCRYPTION_KEY is not a valid Fernet
  key")`. It names the variable and never the value (`hide_input_in_errors` is
  already on). An invalid key stops the server at startup, as the guidelines
  say.
- **Unset is allowed.** The server starts without the key, and only
  `store_upload` and `load_upload` fail, with `upload_key_missing`. That is the
  rule the owner set for this item.
- `.env.example`: the name and a comment, with no value:
  `PORTAL_UPLOAD_ENCRYPTION_KEY=` and "Fernet key for the statement uploads
  (BE-04). Generate it once on your machine; never commit it. Unset: uploads
  answer 503."

### 3.5 Key handling, rotation and limits

- **Generation.** The owner runs once, on the owner's machine:
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`,
  and stores the value in the host's secret store (section 4, After merge). The
  agent never sees the value.
- **Key loss.** Losing the key makes every stored blob unreadable. The only
  effect is on `failed` statements, which then need a new upload. Ready statements
  hold no blob. The owner should know this before the key is set in production.
- **Key rotation is out of scope.** This item supports one key. Rotation would
  use `MultiFernet` with a list of keys and a re-encrypt job. That is a later
  item, and it is not designed here.
- **Authenticity and binding.** Fernet authenticates the token (HMAC), so a
  changed byte or a wrong key gives `upload_unreadable`. Fernet has no associated
  data, so a blob copied from one statement to another would still open. This
  needs database write access, which only the backend role has, so it is an
  accepted residual risk (section 6, question 1).
- **Size.** `MAX_PDF_BYTES` is 10 MiB, the "Até 10 MB" of FE-03. BE-03 refuses a
  larger file before it reaches this module, with its own 413, and imports
  `MAX_PDF_BYTES` from here. `store_upload` refuses it again as a second check. The
  stored token is about 13.4 MiB for a full 10 MiB file, which `bytea` holds. The
  `app_backend` role has `statement_timeout = 15s` and `idle_in_transaction_session_timeout = 30s`
  (`0001_baseline.py`), so the store must be one short statement, and the test in
  section 5 writes a 10 MiB blob to prove it fits.

### 3.6 Ordering with BE-07

BE-04 does not wait for BE-07's code. It waits for its migration number:
`0008` must be the head, so that `0009` follows it. If BE-07 is not merged when
this is implemented, the implementer stops and asks the owner, and does not
renumber or reuse `0008`.

### 3.7 Steps

Estimated at about 400 lines: migration and model about 60, module about 130,
settings and `.env.example` about 30, requirements about 5, tests about 200. **One step, one PR to `main`**, branch
`feat/be-04-upload-retention`, from `origin/main`. If the code passes 500 changed
lines, the split is at the seam between schema and code:

- **Step 1** (`feat/be-04-step-1-upload-schema`): migration `0009`, the model,
  the setting, `.env.example`, the requirements and their tests.
- **Step 2** (after step 1, PR to the feature branch): `server/uploads.py` and
  its tests.

### 3.8 Files

| File | Change |
|---|---|
| `app/api/migrations/versions/0009_statement_uploads.py` | New: table, check, FK, RLS, downgrade (3.1) |
| `app/api/server/db/models.py` | Add `StatementUpload` (`statement_id` pk, `ciphertext: LargeBinary`, `created_at`) |
| `app/api/server/uploads.py` | New: `MAX_PDF_BYTES`, `UploadError`, `seal_pdf`, `open_pdf`, `store_upload`, `load_upload`, `wipe_upload` |
| `app/api/server/settings.py` | `upload_encryption_key` and its validator (3.4) |
| `app/api/.env.example` | Name and comment for `PORTAL_UPLOAD_ENCRYPTION_KEY` |
| `app/api/requirements.in` | Add `cryptography` (no version, as `BACKEND_GUIDELINES` says) |
| `app/api/requirements.txt` | Recompiled with `uv pip compile`; see section 7 |
| `app/api/tests/test_uploads.py` | New, no database (section 5) |
| `app/api/tests/test_uploads_db.py` | New, marker `db` (section 5) |
| `app/api/tests/test_settings.py` | Two cases added (section 5) |
| `docs/BACKEND_GUIDELINES.md` | Data section: one sentence on the retention rule and a link to this spec (3.9) |
| `docs/BACKLOG.md` | Not changed by this spec. At implementation: BE-04 to In progress, then the PR link. Its **Depends on** for BE-04 should add BE-07 (see section 6, gaps) |

No route, no change to `server/main.py`, no change to `test_access_routes.py`.
Nothing is written to disk: the module uses memory and the database only.

### 3.9 Documentation

- `CLAUDE.md`, "Uploaded PDFs are sensitive": **unchanged, and still true.** The
  PDF is not in the repo, `input/` and `outputs/` are not served, and it is not
  in the image. The encrypted blob is in the database, not on the disk.
- `docs/BACKEND_GUIDELINES.md`, "Data and third parties": add one sentence:
  "An uploaded PDF is kept only as an encrypted blob (BE-04), and only while its
  statement is not `ready`."

## 4. Verification

Every check runs when this item merges, with only the item and its Depends on
(BE-07 merged, so the head is `0008`). Commands run from `app/` unless shown.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: the head is `0008` after BE-07 | `cd app && make db-up && make db-current` prints `0008 (head)` |
| 1 | Full API tests | `cd app && make test-api` passes, `db` tests deselected |
| 2 | Database tests, including the migration drift and grant tests | `cd app && make test-db` passes, including `test_uploads_db.py` and `test_migrations_db.py` |
| 3 | Module tests, no database | `cd app/api && .venv/bin/python -m pytest tests/test_uploads.py -v` passes (all cases of section 5.1) |
| 4 | Settings: the server starts with no key and refuses a bad one by name | `cd app/api && .venv/bin/python -m pytest tests/test_settings.py -v` passes, including `test_upload_key_is_optional` and `test_invalid_upload_key_names_the_variable_only` |
| 5 | The migration SQL, offline (no database, no URL) | `cd app && make db-sql FROM=0008` prints `CREATE TABLE portal.statement_uploads`, `ENABLE ROW LEVEL SECURITY` and `CREATE POLICY backend_only ON portal.statement_uploads`, and no error |
| 6 | The pinned package is the one already in use | `cd app/api && uv pip compile requirements.in --python-version 3.14 -o "$TMPDIR/req.txt" && diff requirements.txt "$TMPDIR/req.txt" && echo same`. Expected: `same`, with `cryptography==50.0.2` listed as a direct requirement |
| 7 | The key is not in the repo | `cd app && git grep -n "gAAAA" -- . ':!*.md'` prints nothing (no Fernet token or key in code) |
| 8 | Logs carry no bytes or key (also in test 3) | `cd app/api && .venv/bin/python -m pytest tests/test_uploads.py -k no_bytes_or_key -v` passes |

### After merge (deploy)

The owner runs these from `main`. The agent holds no production credential.

1. Read the SQL first: `cd app && make db-sql FROM=0008`. Expected: the output of check 5.
2. Apply it to Supabase with the owner's connection string, as `docs/deploy/supabase.md`
   describes (assumed, section 8, claim 11): `PORTAL_MIGRATION_DATABASE_URL='<owner's>' make db-upgrade`,
   then `PORTAL_MIGRATION_DATABASE_URL='<owner's>' make db-current`, expected `0009 (head)`.
3. In the Supabase SQL editor, confirm the table is locked to the backend role:
   `select relrowsecurity from pg_class where oid = 'portal.statement_uploads'::regclass;` returns `t`.
4. Before BE-03 is deployed (not needed for this item to pass): the owner generates
   the key (3.5) and sets `PORTAL_UPLOAD_ENCRYPTION_KEY` in the host's secret store.
   The check: the API starts, and `GET /healthz` answers `200`.

The item stays *In progress* until step 2 passes. The Done PR records the result.

## 5. Tests

Fictitious data only. The PDF bytes are `b"%PDF-1.4 Fatura Exemplo fictícia"`,
and the statement is the canonical fixture
`app/fixtures/statement-example-2026-09.json`, imported with `import_statement`
(BE-05). The key is generated in the test with `Fernet.generate_key()`, and
`Settings` is built in code (`populate_by_name`), never from `.env`.

### 5.1 `tests/test_uploads.py` (no database)

| Test | Asserts |
|---|---|
| `test_seal_and_open_round_trip` | `open_pdf(seal_pdf(b, k), k) == b` |
| `test_ciphertext_hides_the_pdf` | Neither `b"%PDF"` nor the words of the fixture appear in the token |
| `test_wrong_key_is_unreadable` | `open_pdf` with another key raises `UploadError` with code `upload_unreadable` (smoke test of the Fernet assumption, claim 4) |
| `test_tampered_token_is_unreadable` | A token with one byte changed raises `upload_unreadable` |
| `test_too_large_is_refused_before_the_key` | `MAX_PDF_BYTES + 1` bytes with no key configured: `upload_too_large`, and the fake session is never touched |
| `test_missing_key_fails_only_when_used` | `Settings` with no key builds; `store_upload` and `load_upload` raise `upload_key_missing` |
| `test_store_flushes_and_does_not_commit` | A fake session: one `add`, one `flush`, no `commit` |
| `test_duplicate_store_is_upload_exists` | A fake session whose flush raises `IntegrityError` gives `upload_exists` |
| `test_load_without_row_is_upload_missing` | A fake session returning `None` gives `upload_missing` |
| `test_database_error_is_database_unavailable` | A fake session whose execute raises `OperationalError` with a host name gives `database_unavailable`, and the host is in neither the exception text nor the captured log |
| `test_no_bytes_or_key_in_errors_or_logs` | For every code: `str(exc)` and `caplog` contain neither the key nor the PDF bytes |

### 5.2 `tests/test_uploads_db.py` (marker `db`, local Postgres as `app_backend`)

| Test | Asserts |
|---|---|
| `test_store_load_wipe_round_trip` | Store a 10 MiB fictitious PDF for a fixture statement, load it back equal, wipe it, and `load` then gives `upload_missing` |
| `test_wipe_is_idempotent` | Second `wipe_upload` returns `False` and raises nothing |
| `test_deleting_the_statement_removes_the_upload` | `session.delete(statement)` (BE-15's hard delete, through the ORM) leaves no row in `statement_uploads` |
| `test_row_is_not_readable_without_the_backend_role` | `SELECT` on `portal.statement_uploads` as the owner role's test connection returns nothing (RLS), as the drift test already checks for every table |

### 5.3 `tests/test_settings.py` (two cases added)

| Test | Asserts |
|---|---|
| `test_upload_key_is_optional` | `Settings()` with no `PORTAL_UPLOAD_ENCRYPTION_KEY` builds, and the field is `None` |
| `test_invalid_upload_key_names_the_variable_only` | A value that is not a Fernet key raises an error that contains `PORTAL_UPLOAD_ENCRYPTION_KEY` and not the value |

The existing migration tests (`test_migration_files.py`, `test_migration_guards.py`,
`test_migrations_db.py`) cover 0009 with no edit: the sequence, the downgrade, the
RLS policy, the grants and the match between the models and the migrated schema.

## 6. Open questions

Each has a recommended option. The owner is away, so each recommendation is
adopted, as delegated: the owner is away; the recommendation will be adopted.

1. **Fernet, or AES-GCM with the statement id as associated data?**
   *Recommended: Fernet, as the handoff decided.* It is in `cryptography`, already
   pinned, and small to test. It gives no binding to the statement id. The
   residual risk is in 3.5 and needs database write access. The alternative,
   AES-GCM with the statement id as associated data, closes it, at the cost of a
   nonce column and more code. (delegated: the owner is away; the recommendation will be adopted)
2. **An explicit `GRANT` in 0009, or the default privileges of 0001?**
   *Recommended: no explicit grant, as `0004` and `0005` do.* The drift test
   checks it. The alternative is an explicit `GRANT SELECT, INSERT, UPDATE, DELETE
   ... TO app_backend`, which is clearer to read and costs one line. (delegated: the owner is away; the recommendation will be adopted)
3. **The setting's name.** *Recommended: `PORTAL_UPLOAD_ENCRYPTION_KEY`.* The
   guidelines require the `PORTAL_` prefix on every setting. The handoff's
   shorter `UPLOAD_ENCRYPTION_KEY` is not used, for that reason. (delegated: the owner is away; the recommendation will be adopted)
4. **Key validation at startup, or at first use?** *Recommended: format checked
   at startup when the key is set, presence checked at first use.* An unset key
   lets the server start, as the owner asked. A malformed key is a configuration
   error, and it stops the server as every other invalid setting does. (delegated: the owner is away; the recommendation will be adopted)
5. **Does the module read the settings itself?** *Recommended: yes, through
   `get_settings()`, with an optional `settings=` keyword for tests.* It keeps the
   call sites short. The alternative is to pass the key in on every call, which
   makes the callers handle the key. (delegated: the owner is away; the recommendation will be adopted)
6. **How long does a failed statement keep its PDF?** *Recommended: until it is
   retried or deleted, with no time limit in this item.* This is the handoff's
   decision. An expiry (for example, purge a `failed` blob after N days) is a
   privacy choice for the owner, and it needs BE-07's failure timestamp, which is
   not in the vocabulary. This is an **owner attention point**. (delegated: the owner is away; the recommendation will be adopted)
7. **Merge order with BE-07.** *Recommended: BE-04 merges after BE-07, so `0008`
   exists.* The alternative, taking `0006` now, would break the reserved numbers of
   BE-13, BE-09 and BE-07 and the sequence test. (delegated: the owner is away; the recommendation will be adopted)

### Gaps for the owner

- **Backlog dependency.** BE-04's row lists **Depends on** `—`. It should list
  BE-07, for the migration order (3.6). This spec does not edit the backlog.
- **BE-03 and BE-08 specs.** Both are Draft. They must adopt the table in 3.2. The
  rule "not ready" is only enforced there, so a spec that stores or reads a blob
  without that table is wrong.
- **Deleting a statement from the table.** `ON DELETE CASCADE` removes the row,
  but the deleted bytes may stay in dead tuples, in the write-ahead log and in
  backups until they are vacuumed or expire (section 8, claim 7). The owner should
  know this before saying a deleted PDF is gone.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-07 merged, so `0008` exists and is the head | Agent (BE-07 owner) | `cd app && make db-up && make db-current` | `0008 (head)` |
| BE-28 merged (the `statements` table) | Agent | `cd app/api && grep -c 'statements' migrations/versions/0004_statements.py` | `2` or more |
| `cryptography` already in the environment and the lock | Agent | `cd app/api && grep -n '^cryptography==' requirements.txt` | `cryptography==50.0.2` |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| The owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted (2026-11-21, delegated) |
| The production key, generated and stored on the host | Owner | (none, before BE-03 deploys) | Not needed for this item to pass |

**Packages.** `cryptography`, a direct runtime dependency. It is already
installed as a dependency of `pyjwt[crypto]` at `cryptography==50.0.2`
(`requirements.txt`, line "via pyjwt"). This item lists it in `requirements.in`
with no version, as `BACKEND_GUIDELINES.md` requires, and recompiles
`requirements.txt` with `uv pip compile requirements.in --python-version 3.14 -o
requirements.txt`. The result should be the same pin, with the comment "via
-r requirements.in" added (check 6). The request for an *exact pin* in the .in
file is met by the `.txt`, where every version is `==`. No new package is added.

**Actions that need the owner's explicit OK.** Applying migration `0009` to
Supabase (After merge, step 2), and setting the production key (After merge,
step 4). Both are the owner's. Nothing else beyond the PR.

**Cost.** None. No new service.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `cryptography` is pinned at 50.0.2 and installed in `app/api/.venv` | *Verified*, `app/api/requirements.txt` (`cryptography==50.0.2`, "via pyjwt"), and BE-23's preflight | Check 6 |
| 2 | The default privileges of `0001_baseline.py` grant DML to `app_backend` on tables created later in `portal` | *Verified*, `0001_baseline.py` lines 45 to 52 | Check 2, the grant test in `test_migrations_db.py` |
| 3 | `enable_backend_only_rls` produces RLS and the single `backend_only` policy | *Verified*, `app/api/migrations/helpers.py` | Check 2 (drift test) |
| 4 | Fernet's `decrypt` raises `InvalidToken` for a wrong key and for a changed byte | *Assumed* from the `cryptography` documentation | `test_wrong_key_is_unreadable` and `test_tampered_token_is_unreadable`; the first real run is the smoke test, in step 1 |
| 5 | `Fernet(key)` raises `ValueError` for a malformed key, and `Fernet.generate_key()` returns bytes | *Assumed* | `test_invalid_upload_key_names_the_variable_only` |
| 6 | A `bytea` of about 13.4 MiB is stored and read back in one statement inside `statement_timeout` = 15 s | *Assumed*, the `bytea` limit is 1 GB and the timeout is *verified* in `0001_baseline.py` | `test_store_load_wipe_round_trip` (10 MiB) |
| 7 | Deleted rows leave their bytes in dead tuples, WAL and backups until vacuum and backup expiry | *Assumed*, standard PostgreSQL MVCC behavior; not testable here | Gap in section 6, recorded for the owner |
| 8 | `ON DELETE CASCADE` on `statement_id` removes the blob when a statement is deleted through the ORM | *Assumed* from the FK definition; the same pattern as `transactions` (`0005`) | `test_deleting_the_statement_removes_the_upload` |
| 9 | A duplicate primary key on flush raises `sqlalchemy.exc.IntegrityError`, which `store_upload` maps to `upload_exists` | *Assumed* (the pattern of `server/statements.py`, line 364) | `test_duplicate_store_is_upload_exists` |
| 10 | The module's `session.flush()` runs inside the caller's transaction, so a rollback removes the blob | *Assumed* from the SQLAlchemy session model | `test_store_flushes_and_does_not_commit`, plus the BE-03 test of "no statement without a blob" |
| 11 | Supabase accepts the migration through `make db-upgrade` with the owner's `PORTAL_MIGRATION_DATABASE_URL`, as `docs/deploy/supabase.md` describes | *Assumed*; I did not open that document in this spec | The owner's step 2 in section 4 |

## 9. Notes for the implementer

- `seal_pdf` and `open_pdf` are pure and take the key as an argument. Only
  `store_upload` and `load_upload` read settings. That is what makes the tests of
  5.1 need no database.
- Never `print`, `repr` or log a `UploadError`'s cause. Its `str` is the code.
- The table has no index beyond the primary key. Lookups are by `statement_id`.
- `wipe_upload` does not check a status. BE-03 calls it in the same transaction as
  the `ready` update. A test in BE-03 checks that a `ready` statement has no row.
