# Spec — BE-03 Upload a statement PDF and run the extraction server-side

| | |
|---|---|
| **Backlog** | Feature: Statement upload and processing › BE-03 |
| **Story** | FE-03 (upload, Draft). FE-04 and FE-14 show the status it sets; BE-08 retries it |
| **Depends on** | BE-04 (**Draft, no spec yet**), BE-05 (Done), BE-07 (**Draft, no spec yet**), BE-24 (Done). The backlog row lists only BE-04 and BE-05: BE-07 and BE-24 are added here and the owner updates the row |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

A person sends a card statement PDF to the portal, and the server does the
rest: it keeps the PDF only as an encrypted blob (BE-04), creates the
statement as `processing`, sends the PDF to Claude with the extraction prompt,
and imports the answer through the import of BE-05. The browser never holds
the Anthropic key and never sees the model's output. `POST /api/statements/upload`
answers `202` at once, and the extraction runs in the background. Its result
is `ready` (the lines are stored and the PDF blob is wiped) or `failed` with a
fixed `failure_code` (the blob is kept, so BE-08 can retry without a new upload).

## 2. Scope

**In scope**

- `POST /api/statements/upload`: the multipart route, its checks, its `202`.
- The extraction module `server/extraction.py`: the client `Protocol`, the real
  Anthropic client, the prompt, the parsing of the answer, and `run_extraction`,
  the background job (BE-08 calls the same job).
- The refactor of BE-05's import so that it can store into a row that already
  exists (section 3.4). BE-05's behavior and tests do not change.
- Settings and the concurrency limit (3.5).
- Moving the extraction prompt into `app/api` and removing the root
  `ask_pdf.py` (section 3.8, step 3).
- Tests (section 5).

**Out of scope**

- The blob itself (encryption, key, table, wipe): BE-04. BE-03 calls its
  functions (section 8, claim 1).
- The status column, the `failure_code` vocabulary and the pt-BR reasons: BE-07.
  BE-03 writes them (section 3.6).
- Listing, retry, card name, export and delete: BE-06, BE-08, BE-09, BE-14, BE-15.
- Decryption of a password-protected PDF and any password input. The root
  `ask_pdf.py` has `-p`; the server does not take a password (section 6, question 2).
- Any screen: FE-03 and later.

## 3. Design

### 3.1 The route

`POST /api/statements/upload`, `multipart/form-data`, one part named `file`.
Behind the Access check (BE-23, application-wide) and `Depends(current_user)`
(BE-24). The statement belongs to the token's user, never to a user id from
the request. The route lives in a new module, `server/routes/uploads.py`.

The checks run in this order. The first failure answers, and nothing after it
runs.

| # | Check | Failure |
|---|---|---|
| 1 | Access and the user (BE-23, BE-24) | 401, 403, 503 as they are |
| 2 | `PORTAL_ANTHROPIC_API_KEY` is set | `503 extraction_unavailable`. Nothing is read, no row is created |
| 3 | `Content-Length` (when given) at most `PORTAL_STATEMENT_MAX_BYTES` plus 64 KiB of multipart overhead; then the bytes read are checked the same way | `413 payload_too_large` |
| 4 | The body parses as multipart, with exactly one part named `file` | `422 invalid_upload` |
| 5 | The part's `Content-Type` is `application/pdf` and its first five bytes are `%PDF-` (offset 0 only) | `415 unsupported_file_type` |
| 6 | The file has no `/Encrypt` marker (a plain byte search over the whole file) | `422 pdf_encrypted` (section 6, question 2) |
| 7 | Under the per-user lock (3.5): at most `PORTAL_MAX_PROCESSING_STATEMENTS` statements in `processing` | `429 too_many_uploads` |
| 8 | One transaction: the statement row (`status` `processing`, `name` from 3.3) and the blob (BE-04's `store_upload`) | `503 database_unavailable` on a `DBAPIError` (BE-24's message) |

On success the route adds `run_extraction` as a `BackgroundTasks` task and
answers `202`:

```json
{"id": "6f1c0e52-...-uuid", "status": "processing"}
```

`Cache-Control: no-store`. The response names no file name, no size and no
statement name.

The uploaded file name (`UploadFile.filename`) is never stored and never
logged (BACKEND_GUIDELINES, Logging, and BE-21). The file's bytes are never
written to disk: the request is read in memory, bounded by the limits above.

### 3.2 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 413 | `payload_too_large` | `O arquivo é maior que 10 MB.` |
| 415 | `unsupported_file_type` | `Envie um arquivo PDF.` |
| 422 | `invalid_upload` | `O envio não tem um arquivo PDF.` |
| 422 | `pdf_encrypted` | `O PDF está protegido por senha. Envie uma cópia sem senha.` |
| 429 | `too_many_uploads` | `Há faturas sendo classificadas. Aguarde antes de enviar outra.` |
| 503 | `extraction_unavailable` | `A classificação não está disponível agora. Tente de novo mais tarde.` |
| 503 | `database_unavailable` | from BE-24, unchanged |

No message carries a file name, a size in bytes or a value from the PDF.
`10 MB` is the limit's text, not a value of the request.

### 3.3 The statement row at upload

The row is created in `processing`, with `user_id` from the token, `total_lanc_atuais`
`NULL` and `name` set to `Fatura enviada em DD/MM/AAAA` (the date of the upload
in `America/Sao_Paulo`). `name` is needed because `statements.name` is not
null and is not empty (BE-28). The name is kept after the import, and BE-09
later adds the card's name beside it. Section 6, question 1 records the choice.

### 3.4 The refactor of BE-05's import

BE-05's `import_statement(session, user, payload)` creates the row and stores
the lines. BE-03 needs the storing part alone, into a row it created, so the
function is split. Nothing else changes:

- `check_payload(session, payload)`: rule 8 (the categories, read from the
  table) and rule 9 (the sum), raising `StatementRefused` as today. It writes
  nothing.
- `store_lines(session, statement, payload) -> Imported`: sets
  `statement.total_lanc_atuais` and inserts the transactions (one `insert` for
  all lines, as today). It does not commit. The caller commits.
- `import_statement(session, user, payload)`: `check_payload`, then creates the
  `Statement`, then `store_lines`, then commits, rolling back on any error. Its
  signature, its refusals and its `201` are those of BE-05.

BE-03 calls `check_payload` and `store_lines` inside its own transaction
(3.6), so the status change and the blob wipe commit with the lines.

### 3.5 Limits and concurrency

Settings (3.8 names them) and their defaults:

- `PORTAL_STATEMENT_MAX_BYTES`: `10485760` (10 MiB, the prototype's limit).
- `PORTAL_MAX_PROCESSING_STATEMENTS`: `2`, per user.
- `PORTAL_ANTHROPIC_MODEL`: `claude-sonnet-5-5` (the default of `ask_pdf.py`).

The count lives in `check_processing_limit(session, user)` in `server/uploads_limits.py` (BE-08 calls it too, and it raises the 429 `too_many_uploads`). The extraction client comes from the dependency `get_extraction_client(settings)`, which tests override. The count of the user's `processing` statements is taken under a
transaction-scoped advisory lock on the user (`pg_advisory_xact_lock` on a hash
of the user's id), so two uploads of the same person cannot both pass the
count. The lock needs no grant beyond what `app_backend` has (section 8,
claim 6). Before the count, the same transaction marks the user's stale
statements as failed: `processing` for longer than 15 minutes becomes
`failed` with `failure_code` `interrupted`. That covers a process that stopped
during an extraction, with no startup job and no connection at startup
(BE-24's rule).

### 3.6 The background job

`run_extraction(engine, statement_id, client, model)` is a plain `def`. Starlette
runs it in the threadpool, and BE-08 calls it with the same arguments. It opens
its own `Session` from `engine`, because the request's session is closed before
the background task runs.

1. Read the statement by id (the user is not needed: the id came from a
   request that the route already checked). Read `portal.categories` codes.
2. Load the blob (BE-04's `load_upload`). A missing blob is `interrupted`.
3. `client.extract(pdf_bytes, categories)` returns the model's text, or raises
   `ExtractionError(code)` (3.7). The blob bytes are dropped after the call.
4. Parse the text as the extraction JSON and build a `StatementPayload`
   (BE-05) with `name` set to the statement's name. A schema failure is
   `extraction_invalid`.
5. `check_payload` (BE-05, rules 8 and 9). A `StatementRefused` becomes the
   failure code of its refusal: `unknown_category` or `total_mismatch`.
6. In one transaction: `store_lines`, set `status = 'ready'`, call BE-04's
   `wipe_upload`, commit.
7. On any failure before step 6 is committed: roll back, set `status = 'failed'`
   and `failure_code` in a new transaction, and leave the blob in place.

The failure codes written here (BE-07 must list them, section 8, claim 2):
`extraction_unavailable`, `extraction_timeout`, `extraction_refused`,
`extraction_truncated`, `extraction_invalid`, `unknown_category`,
`total_mismatch`, `interrupted`.

The pt-BR reason for each code is BE-07's, and FE-04 shows it. No failure text
comes from the model or from an exception message.

### 3.7 The extraction client

`server/extraction.py` defines the seam the tests use:

```python
class ExtractionClient(Protocol):
    def extract(self, pdf: bytes, categories: list[str]) -> str: ...
```

It returns the model's text and nothing else. The real implementation,
`AnthropicExtractor(api_key, model, timeout=600)`, does what `ask_pdf.py` does
without the password step: the PDF as a base64 `document` block, the prompt
text, `output_config` with the JSON schema built from `categories` (the schema
of `ask_pdf.py`, with the enum from the table, section 6, question 5),
`max_tokens=64000`, and `messages.stream(...).get_final_message()`.

The SDK's errors become `ExtractionError` codes, and the log gets the class
name only:

| SDK error or answer | `ExtractionError` |
|---|---|
| `AuthenticationError`, `RateLimitError`, `APIConnectionError`, other `APIStatusError` | `extraction_unavailable` |
| `APITimeoutError` | `extraction_timeout` |
| `stop_reason == "refusal"` | `extraction_refused` |
| `stop_reason == "max_tokens"` | `extraction_truncated` |
| no text block | `extraction_invalid` |

`ANTHROPIC_API_KEY` is read from `PORTAL_ANTHROPIC_API_KEY` (a `SecretStr`), not
from the SDK's own environment variable, so every setting has the portal's
prefix (`docs/BACKEND_GUIDELINES.md`, Settings). The key is passed to the client
in code and never printed.

No test calls the network. The tests inject a fake `ExtractionClient`.

### 3.8 Files, settings and steps

**Settings** (`server/settings.py`, and the names in `.env.example`, no value):

| Variable | Type | Default |
|---|---|---|
| `PORTAL_ANTHROPIC_API_KEY` | `SecretStr \| None`, blank is unset | none |
| `PORTAL_ANTHROPIC_MODEL` | `str`, non-empty | `claude-sonnet-5-5` |
| `PORTAL_STATEMENT_MAX_BYTES` | `int`, 1 to 10485760 | `10485760` |
| `PORTAL_MAX_PROCESSING_STATEMENTS` | `int`, 1 to 10 | `2` |

**Packages** (exact pins, the newest release at least two weeks old on
2026-11-21, checked on PyPI):

| Package | Pin | Released | Why |
|---|---|---|---|
| `anthropic` | `==2.6.0` | 2026-11-05 | The client of 3.7 |
| `python-multipart` | `==0.0.33` | 2026-10-31 | Starlette's form parsing (3.1) |

`anthropic` and `python-multipart` go in `requirements.in` without versions,
and `requirements.txt` is compiled with `uv pip compile` for Python 3.14. The
newer releases (`anthropic` 2.12.0, `python-multipart` 0.0.34) are not used
because they are under two weeks old. `cryptography` is BE-04's package
(Fernet); it is not listed here.

**Steps.** Three pull requests, all under 500 changed lines. The item cannot
fit in one: the code of 3.1 to 3.7, the tests and the prompt come to about
800 lines. Feature branch `feature/be-03-upload-and-extract` from `origin/main`,
created when implementation starts. Each step is a branch from it, and its PR
targets it. The final PR takes the feature branch to `main`. This spec is a
separate docs PR to `main`, as BE-12's spec was.

- **Step 1** (`feat/be-03-step-1-extraction-module`, PR to the feature branch,
  about 420 lines): the settings and `.env.example`; the packages; the split of
  BE-05's import (3.4), with BE-05's tests unchanged; `server/extraction.py`
  with the Protocol, `AnthropicExtractor`, the parsing and `run_extraction`
  (3.6, 3.7); the prompt copied to `app/api/server/prompts/prompt-pdf.md`.
  No route.
- **Step 2** (`feat/be-03-step-2-upload-route`, PR to the feature branch,
  about 380 lines): `server/routes/uploads.py` with the checks of 3.1, the
  limits and the lock of 3.5, the registration in `server/main.py`, and the
  `BackgroundTasks` wiring; `docs/BACKEND_GUIDELINES.md` (Layout).
- **Step 3** (`chore/be-03-step-3-remove-ask-pdf`, PR to the feature branch,
  about 300 lines, all deletions): removes the root `ask_pdf.py` and
  `prompt-pdf.md`. It runs only after step 2 is merged and the owner has
  confirmed that the portal replaces the CLI.

If step 1 passes 500 lines, the split is at `store_lines` (3.4): the refactor
goes first, the client second.

**Files**

| File | Change | Step |
|---|---|---|
| `app/api/server/settings.py` | Four settings (3.8) | 1 |
| `app/api/.env.example` | Four names, no values | 1 |
| `app/api/requirements.in`, `requirements.txt` | Two packages (3.8) | 1 |
| `app/api/server/statements.py` | `check_payload`, `store_lines`; `import_statement` calls them | 1 |
| `app/api/server/extraction.py` | New: `ExtractionClient`, `ExtractionError`, `AnthropicExtractor`, `parse_extraction`, `run_extraction` | 1 |
| `app/api/server/prompts/prompt-pdf.md` | Copy of the root `prompt-pdf.md`, byte for byte | 1 |
| `app/api/server/routes/uploads.py` | New: `POST /api/statements/upload` | 2 |
| `app/api/server/main.py` | Register the `uploads` router | 2 |
| `docs/BACKEND_GUIDELINES.md` | Layout: `extraction.py`, `routes/uploads.py`, `prompts/` | 2 |
| `ask_pdf.py`, `prompt-pdf.md` (root) | Removed | 3 |

No migration: BE-03 adds no table or column. Its schema needs are BE-04's
(`statement_uploads`, migration 0009) and BE-07's (`status`, `failure_code`,
migration 0008). Both are applied by their own deploy checks.

## 4. Verification

Everything runs when the item's last PR merges, with the local Postgres
(`make db-up`), and with BE-04 and BE-07 merged, as the Depends on line requires.
The tests use fakes for Access, for the Anthropic client and for the blob
functions of BE-04 when a test needs them out of the way.

`make test-api` passes no arguments, so single files run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-04 and BE-07 are Done | `cd app/api && grep -c "statement_uploads" server/db/models.py && grep -c "failure_code" server/db/models.py` | Both print a number above `0` |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected, including BE-05's tests unchanged |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_upload_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_extraction.py -v` | All pass (section 5.1) |
| 4 | `cd app/api && .venv/bin/python -m pytest tests/test_uploads_route.py -v` | All pass (section 5.2) |
| 5 | `cd app/api && .venv/bin/python -m pytest -m db tests/test_uploads_db.py -v` (with `PORTAL_DATABASE_URL` for `app_backend`) | All pass (section 5.3) |
| 6 | `grep -E '^(anthropic\|python-multipart)==' app/api/requirements.txt` | Two lines: `anthropic==2.6.0` and `python-multipart==0.0.33` |
| 7 | `cmp app/api/server/prompts/prompt-pdf.md prompt-pdf.md` (steps 1 and 2) | No output, exit `0` |
| 8 | Step 3 only: `test ! -e ask_pdf.py && test ! -e prompt-pdf.md && echo gone` | `gone` |
| 9 | `grep -rn "print(\|log_event" app/api/server/extraction.py app/api/server/routes/uploads.py` reviewed by hand | Only `log_event` calls with the event names of section 9; no call logs a file name, bytes, a description or model text |

### After merge (deploy)

These run from `main` after the owner deploys. The agent does not connect to the host.

| # | Owner runs | Expected |
|---|---|---|
| D1 | `ssh <host> 'sudo grep -c ^PORTAL_ANTHROPIC_API_KEY= /etc/odiservices/.env'` | `1` (the count only, never the value) |
| D2 | Open the portal in the browser signed in through Access, and send a `.txt` file renamed to `.pdf` through the upload area | `415`. No statement row is created (`select count(*) from portal.statements` unchanged) |

**Pending validation** (the owner's real statement, owner present, through the
running portal; the result is recorded as "validated on <date>", with no data):
one real statement goes through the upload, reaches `ready`, and its
transactions and total match the statement. The item is *Pending validation*
until then; no real statement is used in a check or a test.

## 5. Tests

Fictitious data only. The canonical fixture `app/fixtures/statement-example-2026-09.json`
is the extraction shape of BE-05 without `name`, and it is the model's answer
in the fake client. The PDF is a fictitious byte string, `b"%PDF-1.4\n% fictitious\n%%EOF\n"`,
generated in the test. The access check uses `tests/access_helpers.py` with the
verifier faked, as in BE-24. The fake client records its calls and returns a
canned answer or raises an `ExtractionError`. No call leaves the machine.

### 5.1 `tests/test_extraction.py` (no database)

| Test | Asserts |
|---|---|
| `test_prompt_copy_is_the_root_prompt` | The copy is byte-for-byte equal to `prompt-pdf.md` at the repo root while both exist (step 1 and 2 only; removed with step 3) |
| `test_prompt_categories_are_the_seeded_codes` | The category line of the prompt lists exactly the ten codes of `portal.categories` (fixture list in the test) |
| `test_fixture_parses_to_a_payload` | The canonical fixture, as answer text, parses and validates to `StatementPayload` |
| `test_bad_json_is_extraction_invalid` | A non-JSON answer gives `ExtractionError("extraction_invalid")` |
| `test_schema_violation_is_extraction_invalid` | An answer with an extra field gives `extraction_invalid` |
| `test_sdk_errors_map_to_codes` | With a stub SDK that raises each error class: `AuthenticationError`, `RateLimitError`, `APIConnectionError` give `extraction_unavailable`; `APITimeoutError` gives `extraction_timeout`. The message of the error is not in the exception |
| `test_refusal_and_truncation_map_to_codes` | `stop_reason` `refusal` gives `extraction_refused`; `max_tokens` gives `extraction_truncated` |
| `test_run_extraction_success_stores_and_wipes` | A fake blob store and a fake client with the fixture: the statement is `ready`, 17 lines, the blob is wiped, one commit |
| `test_run_extraction_total_mismatch_is_failed_and_keeps_blob` | One amount changed by R$ 0,01: `failed`, `total_mismatch`, no lines, blob kept |
| `test_run_extraction_unknown_category_is_failed` | One category `XYZ`: `failed`, `unknown_category`, blob kept |
| `test_run_extraction_error_is_failed_with_code` | The fake client raises `extraction_timeout`: `failed`, `extraction_timeout`, blob kept |
| `test_missing_blob_is_interrupted` | The blob store returns `None`: `failed`, `interrupted`, no client call |
| `test_no_key_is_unavailable` | `AnthropicExtractor` is not built when the key is absent (the factory returns `None`), and `run_extraction` with no client gives `failed`, `extraction_unavailable` |
| `test_logs_carry_no_values` | The fixture's description, an amount and a category text planted in the answer do not appear in any log line (captured) |

### 5.2 `tests/test_uploads_route.py` (app with a fake session, no database)

| Test | Asserts |
|---|---|
| `test_requires_access` | No token: `401`, no extraction call, no row |
| `test_no_key_is_503_and_no_row` | No `PORTAL_ANTHROPIC_API_KEY`: `503 extraction_unavailable`, the session is never written |
| `test_oversized_content_length_is_413` | A `Content-Length` above the limit plus slack: `413`, the body is not read |
| `test_oversized_chunked_body_is_413` | A body above the limit with no `Content-Length`: `413` |
| `test_two_files_or_no_file_is_422` | Zero parts, two `file` parts, or a part named `other`: `422 invalid_upload` |
| `test_wrong_type_is_415` | `Content-Type: text/plain`, or `application/pdf` with bytes not starting `%PDF-`: `415 unsupported_file_type` |
| `test_encrypted_pdf_is_422` | A fictitious PDF byte string containing `/Encrypt`: `422 pdf_encrypted` |
| `test_too_many_processing_is_429` | Two statements `processing` for the user (fake count), N = 2: `429 too_many_uploads`, no row, no blob |
| `test_accepted_upload_is_202` | A valid fictitious PDF: `202`, body is exactly `{"id", "status": "processing"}`, `Cache-Control: no-store`, the background job ran once with the statement id |
| `test_error_bodies_carry_no_file_name_or_bytes` | A planted file name `Fatura Exemplo Secreta.pdf` and the PDF's text do not appear in any error body or log line |
| `test_upload_logs_carry_no_values` | The `202` and each refusal log only the route template, the status and the event names of section 9 |

### 5.3 `tests/test_uploads_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_upload_creates_processing_row_and_blob` | One statement for the token's user in `processing`, `total_lanc_atuais` null, the `name` of 3.3, one blob row (BE-04), then the background job runs (the fake client returns the fixture): the statement is `ready`, 17 transactions, the blob row is gone |
| `test_failed_extraction_keeps_blob_and_retry_data` | The fake client answers a total mismatch: `failed`, `total_mismatch`, zero transactions, the blob row still there |
| `test_stale_processing_is_interrupted` | A `processing` row created 20 minutes ago: the next upload of the user marks it `failed` with `interrupted` before the count |
| `test_lock_serialises_the_count` | Two threads send an upload each with N = 1: exactly one gets `202`, the other `429`, one `processing` row |
| `test_other_users_processing_is_not_counted` | Another user's two `processing` rows do not block this user's upload |
| `test_app_role_can_run_the_flow` | The whole flow works as `app_backend` with RLS on, with the grants of BE-04, BE-07 and BE-28 |

## 6. Open questions

Each question has a recommendation. The owner is away, so the recommendations
are adopted as assumptions (delegated: the owner is away; the recommendation
will be adopted).

1. **The name of the new row.** *Recommended: `Fatura enviada em DD/MM/AAAA`,
   with the date of the upload in `America/Sao_Paulo`, kept after the import.*
   The uploaded file name is not used: it can hold a card or a person (BE-21),
   and the extraction does not return a name. FE-03 leaves the row's name
   before classification open (its "not covered yet" list). The alternative is
   a fixed `Fatura em processamento` until success, which gives every row the
   same name.
2. **Password-protected PDFs.** *Recommended: no password input. A PDF with a
   `/Encrypt` marker is refused at upload with `422 pdf_encrypted`, and the
   owner decrypts a copy locally.* The root `ask_pdf.py` decrypts with
   `pymupdf` and a `-p` password. Sending a password to the API puts a secret
   in the browser, and `pymupdf` is a new dependency that no spec lists. The
   marker check is a byte search, so it can refuse a plain PDF that contains
   the text `/Encrypt`; the owner can then send a copy saved without
   protection. The alternative is `pymupdf` and a password field, which needs
   a new spec for the package and the field.
3. **The limit of processing statements.** *Recommended: 2 per user, a setting.*
   It stops a double click from starting two paid extractions. It is a
   per-user count, not a global queue. A queue is a later item if the owner
   wants one.
4. **Where the extraction runs.** *Recommended: FastAPI `BackgroundTasks` in
   the same process, with one uvicorn worker per container.* No queue or
   worker service exists, and the host runs one container of the API (OPS-03).
   A restart leaves `processing` rows, and section 3.5 marks them
   `interrupted` after 15 minutes. The alternative is a worker item, which the
   backlog does not have.
5. **Where the categories of the model's schema come from.** *Recommended: the
   table (`portal.categories`), read at the start of each job, as BE-30 asks
   (the database is the single source of truth). The prompt's category line
   is checked against the table by a test (5.1).* The alternative is the
   prompt's list, which is the duplicate BE-30 removes.
6. **Removing `ask_pdf.py` and the root prompt.** *Recommended: step 3, after
   step 2 is merged and the owner has confirmed the portal replaces the CLI.*
   The CLI wrote to `outputs/`, which BE-03 must not do, and `kanban/` that read
   those files is already gone (BE-17).
7. **Setting names.** *Recommended: `PORTAL_ANTHROPIC_API_KEY`, with the
   portal's prefix.* The brief named `ANTHROPIC_API_KEY`. The portal's settings
   rule (`docs/BACKEND_GUIDELINES.md`, Settings) puts every variable under
   `PORTAL_`, and the owner's secrets list (OPS-05) follows the same names. The
   owner may choose the SDK's name instead; it is a one-line change in 3.7.
8. **The upload limit.** *Recommended: 10 MiB, from `PORTAL_STATEMENT_MAX_BYTES`
   (the prototype's limit, which the backlog asks to enforce here).* The
   `Content-Length` slack is 64 KiB for the multipart envelope.

## 7. Prerequisites

| Prerequisite | Who provides it | Preflight | Expected |
|---|---|---|---|
| BE-04 spec approved and merged (blob functions `store_upload`, `load_upload`, `wipe_upload`, table `statement_uploads`, migration 0009) | Agent (BE-04 item) | Section 4, check 0 | `statement_uploads` and `failure_code` found in the models |
| BE-07 spec approved and merged (`status`, `failure_code`, migration 0008) | Agent (BE-07 item) | Section 4, check 0 | Found |
| Local Postgres at the head revision (0009 after BE-04) | Agent | `cd app && make db-up && make db-current` | `0009 (head)` |
| The canonical fixture exists (BE-05) | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| Local Docker for `make test-db` | Owner | `docker info >/dev/null && echo ok` | `ok` |
| The Anthropic key on the host (deploy only; never in a test, never in the repo) | Owner | After-merge check D1 | `1` |
| Owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted, delegated |

**Packages.** `anthropic==2.6.0` and `python-multipart==0.0.33` (3.8). Listed
here, as CLAUDE.md requires. No other package.

**Actions that need the owner's explicit OK.** Approval of this spec is the
OK for the two packages and for the three pull requests. The deploy (D1, D2)
is the owner's. The owner adds the key to the host outside the repo; the agent
never holds it.

**Cost.** Tests: none. Deploy and the owner's Pending validation send one real
statement to Anthropic, which costs one extraction per run. Each run is the
owner's, with a real statement, and no check in this spec makes that call.

**Definition of Ready (`docs/specs/README.md`), today.** Not green. The spec
is In review. BE-04 and BE-07 have no spec, so the Depends on line is not met.
The rows above this paragraph are the only gaps the spec can list. The owner
must approve this spec, and BE-04 and BE-07 must be specified and approved
before this item starts.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | BE-04 provides `store_upload(session, statement_id, pdf)`, `load_upload(session, statement_id) -> bytes \| None` and `wipe_upload(session, statement_id)`, in the same transaction as the caller | *Assumed*: BE-04 is Draft, with no spec. The names are proposed here and BE-04's spec must match them, or this spec is updated | Section 5.3 `test_upload_creates_processing_row_and_blob`; BE-04's spec is checked against this section when it is written |
| 2 | BE-07 provides `statements.status` (`processing`, `ready`, `failed`) and `failure_code` with the codes of 3.6 | *Assumed*: BE-07 is Draft. The codes are proposed here | Section 5.1 `test_run_extraction_total_mismatch_is_failed_and_keeps_blob` and the codes list in 3.6 |
| 3 | `anthropic==2.6.0` has `messages.stream(..., output_config=...)` and `get_final_message()`, as `ask_pdf.py` uses them with the version the owner has | *Assumed* | Step 1 smoke test: `cd app/api && .venv/bin/python -c "import inspect,anthropic;print('output_config' in inspect.signature(anthropic.Anthropic(api_key='x').messages.stream).parameters)"` prints `True`. No network |
| 4 | Starlette 1.10.0 `Request.form(max_part_size=...)` bounds a part, and `UploadFile` reads bytes without a file on disk | *Assumed* | Step 2 smoke test, and `test_oversized_chunked_body_is_413` |
| 5 | The API runs as one uvicorn worker per container, so `BackgroundTasks` and the in-memory client run in that process | *Assumed* | Step 2: `grep -n "workers\|CMD" app/api/Dockerfile` shows no `--workers` above 1 |
| 6 | `pg_advisory_xact_lock` needs no grant for `app_backend` | *Assumed* from the Postgres documentation (the advisory lock functions are not table privileges) | Section 5.3 `test_lock_serialises_the_count`, run as `app_backend` |
| 7 | A background job that opens its own session from the engine works after the response is sent | *Assumed*, and the design does not rely on the request's session | Section 5.3 `test_upload_creates_processing_row_and_blob` (the job runs after the `202`) |
| 8 | The canonical fixture has the extraction shape without `name`, 17 lines and total `11906.35` | *Verified* in BE-05's spec (3.6) and checked by BE-05's test; the file's presence is preflight | Section 7, the fixture row |
| 9 | Starlette runs a sync background function in the threadpool, so the blocking SDK call does not block the event loop | *Assumed* from Starlette's documentation | Step 2: the job is a `def`, and a test runs the route with the fake client |

## 9. Notes for the implementer

- Keep BE-05's `import_statement` signature and its refusals. The split is
  internal; BE-05's tests must pass without edits.
- The blob never touches the disk, and `run_extraction` drops its bytes as
  soon as the call returns.
- A refusal from `check_payload` is a normal failure with a code. It is not an
  error to log with values; the log has the statement id and the code.
- `run_extraction` is the single job for the first run (BE-03) and the retry
  (BE-08). BE-08 calls it with a `processing` row it has just set, and its own
  checks.
- Log events, all with ids, codes and counts only: `statement_upload_accepted`
  (`statement_id`), `statement_upload_refused` (`code`), `extraction_finished`
  (`statement_id`, `status`, `failure_code`, `transaction_count`, `duration_ms`),
  `extraction_error` (`error` = class name only, `statement_id`). Nothing else.

## Amendments before approval (2026-11-21)

- A statement can be deleted (BE-15) while its job runs. `run_extraction` reads the row first; a missing row ends the job with no error, no status write and no log of values. Add `test_job_ends_quietly_when_the_row_is_gone` to section 5.1.
- The failure vocabulary is the one of BE-07 section 3.4 (eleven codes, amended to include the codes of 3.6).
- `set_status(..., commit=False)` is used for the status change inside the job's transaction (BE-07, amended).
