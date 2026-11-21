# Spec — BE-14 Export a statement

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-14 |
| **Story** | FE-13 (Exportar JSON, `docs/stories/board/FE-13-export-json.feature`, Draft) |
| **Prototype** | `docs/prototypes/portal/v3.html#board` |
| **Depends on** | BE-10 (Done, #89 and #91) |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

The finance team takes the classified statement to the accounting tools. `GET /api/statements/{statement_id}/export` returns the statement as a JSON file in the shape that `POST /api/statements` (BE-05) imports: `name`, `total_lanc_atuais` and `lancamentos`, with each line's current category. The file is the same document the import accepts, so exporting a statement and importing the file gives back the same lines and categories. The route is read-only, for the signed-in user only, and reads the same tables as BE-10. A statement that BE-05 could not have stored is refused with `409` instead of being exported as a file that cannot be imported.

## 2. Scope

**In scope**

- `GET /api/statements/{statement_id}/export`, the functions behind it (`read_export`, `render_export`) and the refusal of a statement that cannot be re-imported (3.2).
- The file: its fields, its money as JSON numbers, its headers (3.3).
- The round-trip guarantee, tested with the fixture (section 5).
- Tests (section 5).

**Out of scope**

- The browser side: the "Exportar JSON" control, the download and the error display: FE-13.
- The review state (`reviewed`) and the category before a user move (`moved_by_user`, BE-13). The file has the BE-05 shape, which has neither field, so they are not exported (section 6, question 5).
- Display labels: the file carries the category codes, as the import does (BE-16 decides labels).
- Card name and last digits (BE-09). When BE-09 adds them to the import, the export gains the same optional fields in the same change (section 9).
- Deleting or changing a statement: BE-15, BE-11.

## 3. Design

### 3.1 The route

`GET /api/statements/{statement_id}/export`, behind the Access check (BE-23, application-wide) and `Depends(current_user)` (BE-24), as BE-10 and BE-12 are. The statement is found by its id and the user in the token, never by a user id. The id is declared as `str` and parsed with `uuid.UUID(...)`, so a malformed id is a `404`, not a `422`. There is no body and no query parameter.

Route order: the path is a new segment under the statement, so it does not collide with BE-10's `GET /api/statements/{statement_id}` or BE-12's `/summary`.

### 3.2 The steps of the read

1. Parse `statement_id`. Malformed: `404 statement_not_found`.
2. `owned_statement` (BE-10): no row for this user gives `404 statement_not_found`. The lines are read only after this.
3. Read the lines `where statement_id = :id order by item_number` (the same query as BE-10, 3.3).
4. Refuse with `409 statement_not_exportable` when the file would not pass BE-05's checks. The checks are: the statement has a total (`total_lanc_atuais` is not null, BE-28 allows null), it has at least one line (BE-05 rule 4), and the sum of the amounts equals the total to the cent (BE-05 rule 9). The sum is computed in `Decimal`. Every other BE-05 rule already holds for stored data: the sections, the category codes (a foreign key), the description and date (check constraints, BE-29), the ids (unique, at least 1, BE-29), the limits of 500 lines and 512 KiB.
5. Render the file (3.3).

A refused statement is `409` with the body of 3.5 and no file. The refusal names no value.

### 3.3 The file

`200`, with these headers:

| Header | Value |
|---|---|
| `Content-Type` | `application/json; charset=utf-8` |
| `Content-Disposition` | `attachment; filename="fatura.json"` (a fixed literal) |
| `Cache-Control` | `no-store` |

The filename is the same for every statement. It carries no statement name, no id and no date, so the header holds no PII (section 6, question 4). The body:

```json
{"name": "Fatura Cartão Exemplo, set/2026", "total_lanc_atuais": 11906.35, "lancamentos": [
  {"id": 1, "secao": "compras", "data": "05/09", "descricao": "Distribuidora Exemplo Ltda", "valor": 1250.00, "categoria": "FORNECEDOR", "duvida": false},
  ...
]}
```

The exact rules:

- **Fields.** Only the fields of BE-05's request (3.1 of that spec): top level `name`, `total_lanc_atuais`, `lancamentos`; per line `id`, `secao`, `data`, `descricao`, `valor`, `categoria`, `duvida`. No statement id, no `reviewed`, no `created_at`, no `moved_by_user`. BE-05 refuses unknown fields, so the file must not carry any.
- **`id`** is the stored `item_number`, as stored (gaps stay). **`secao`** maps back: `purchases` to `compras`, `international` to `internacional`, `products` to `produtos`. The map is the inverse of BE-05's `SECTIONS` in `server/statements.py`, and the code defines it once, from that dict, so the two cannot drift.
- **`data`**, **`descricao`** are the stored text. **`categoria`** is the stored `category_code`, which is the current category, so a line moved on the board is exported in its new category (FE-13's scenario).
- **`duvida`** is the stored `doubtful`, a JSON boolean.
- **Money is a JSON number, not a string.** This is the one place where money is not a decimal string. BE-05 reads `valor` and `total_lanc_atuais` only as JSON numbers: `as_decimal` refuses a `str`, a `bool` or a `float` (`server/statements.py`, lines 77 to 82), and `read_payload` parses the body with `json.loads(..., parse_float=Decimal)` (lines 142 to 150). The file therefore writes each money value as `f"{value:.2f}"` without quotes. `1250.00` is then read as `Decimal("1250.00")`, exactly, and the sum check of BE-05 runs on exact values. Section 6, question 2, records the choice.
- **Serialization is written by hand.** Two traps, both named here so that nobody "fixes" them:
  - `JSONResponse` and `json.dumps` cannot take a `Decimal`, and they raise.
  - Pydantic's `model_dump_json()` writes a `Decimal` as a quoted string (`"1250.00"`), which BE-05 refuses with `422 invalid_statement`. The export does not use it.
  The body is built as text: the money with `f"{value:.2f}"`, the strings with `json.dumps(text, ensure_ascii=False)` (which escapes quotes and control characters), the booleans as `true` and `false`, the ids as integers. It is returned with a plain `Response` (`content=bytes`, UTF-8), not `JSONResponse`.
- **Order.** The `lancamentos` list is in `item_number` order, as BE-10 returns the lines.
- **Size.** At most 500 lines, each about 200 bytes, so the file stays under 512 KiB, the limit BE-05 applies to its request.

### 3.4 Ownership and privacy

The export answers for the statement of the token's user only. A foreign and a missing id give the same `404`. The export reads the rows; it writes none.

The file is personal and financial data, so its headers and its logs carry no value (3.6).

### 3.5 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors). Except for the file of 3.3, every error is JSON in that format.

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` (BE-10, unchanged) |
| 409 | `statement_not_exportable` | `Esta fatura não pode ser exportada: ela não tem lançamentos ou um total.` (also used for a sum that does not match the total, which is a stored inconsistency, not a user error) |
| 503 | `database_unavailable` | from BE-24, unchanged. Also for a `DBAPIError` in this route's queries; the log carries the class name only |

The `404` is one answer for an unknown, a malformed and another user's id, with the same body and headers except `X-Request-Id`, as in BE-10.

### 3.6 Logging

The request log of BE-21 is the only line. It records the route template, `/api/statements/{statement_id}/export`, never the raw path. The route writes one `database_error` line on a `DBAPIError` (class name only), and nothing else. No name, description, amount, category or count appears in any line.

### 3.7 Steps

One step, about 400 to 450 lines with the tests and the rendering. Branch `feat/be-14-export-statement`, from `origin/main`, PR to `main`. Earlier items overran their estimates (BE-10 220 to 480 lines, BE-12 550 to 600 estimated). If the code passes about 650 lines, the seam is the rendering (3.3, a pure function) against the route, and that split is proposed before more code is written.

### 3.8 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add `SECTIONS_OUT` (the inverse of `SECTIONS`, built from it), `read_export(session, user, statement_id)` (returns the rendered bytes, `None` for a missing or another user's statement, raises `StatementRefused` for the 409), `render_export(name, total, lines)` (the text of 3.3, pure) |
| `app/api/server/routes/statements.py` | Add `GET /api/statements/{statement_id}/export` with the headers of 3.3 |
| `app/api/tests/test_statement_export.py` | New: section 5, no database |
| `app/api/tests/test_statement_export_db.py` | New: section 5, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-14 to In progress, then the PR link. Not changed by this spec |

No migration (the reads are those of BE-10, and the grants of BE-28 and BE-29 already cover them), no setting, no dependency, no change to `server/main.py`, and no change to `test_access_routes.py` (its every-route test fills the path parameter with a sample id, as BE-12 section 8 claim 2 records).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`). There is no *After merge (deploy)* list: no migration and no deploy. The route is checked through the test client, with the Access verifier faked. No check needs BE-11, BE-13 or BE-16: the moved line is changed through the ORM, as BE-12 does.

`make test-api` passes no arguments to pytest, so single files are run as `cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-10 is merged | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_statement_export_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_export.py -v` | All pass: `test_export_requires_access`, `test_malformed_id_is_404`, `test_export_headers_are_fixed`, `test_money_is_an_unquoted_number`, `test_export_logs_carry_no_values`, `test_no_engine_is_503`, `test_query_error_is_503_without_details`, `test_rendered_export_passes_the_import_model`, `test_text_is_escaped`, `test_money_has_two_places` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_export_db.py -v` | All pass: `test_fixture_round_trips_through_the_import`, `test_moved_line_is_exported_in_its_new_category`, `test_exact_cents_survive_the_round_trip`, `test_empty_or_untotalled_statement_is_409`, `test_sum_mismatch_is_409`, `test_other_users_statement_is_identical_to_missing` |

Check 4 covers the round trip with the canonical fixture and FE-13's scenario: "Correios Demo" (line 10, `DESPESA ADMINISTRATIVA`, 32.40) is moved to `OPERACIONAL` through the ORM, and the file has it as `OPERACIONAL`.

## 5. Tests

Fictitious data only: the canonical fixture, imported through `import_statement` (BE-05), and copies changed in memory where a case needs them. Access and the user row use `tests/access_helpers.py` and the BE-24 pattern, with the verifier faked. No call leaves the machine.

### 5.1 `test_statement_export.py` (no database)

The app and the fakes follow `test_statement_summary.py` (BE-12): overrides for `get_session` and `current_user`, a plain `create_app` where the Access chain itself is under test.

| Test | Asserts |
|---|---|
| `test_export_requires_access` | No token gives `401`, and the export's queries are never reached |
| `test_malformed_id_is_404` | `abc-123`, a uuid one character short and `%20` each give `404` with `statement_not_found`, never `invalid_statement` |
| `test_export_headers_are_fixed` | A `200` has `Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`, and `Content-Disposition` equal to the literal `attachment; filename="fatura.json"`. The name and the id of the statement appear in no header |
| `test_money_is_an_unquoted_number` | The body holds `"valor": 1250.00` and `"total_lanc_atuais": 11906.35`, with no quote around a money value. `json.loads(body, parse_float=Decimal)` gives `Decimal("1250.00")` |
| `test_export_logs_carry_no_values` | The request line holds `"route": "/api/statements/{statement_id}/export"` and no id. A planted name `Fatura Sigilo` and description `Loja Exemplo Sigilo` appear in no log line |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token: `503` with `database_unavailable` |
| `test_query_error_is_503_without_details` | A fake session whose `execute` raises `OperationalError` with a host name: `503`; the host is in neither the body nor the log |
| `test_rendered_export_passes_the_import_model` | Pure: `render_export` of the 17 lines of the fixture, passed to `read_payload`, gives a payload with the same 17 lines and total. This is the round trip without a database |
| `test_text_is_escaped` | Pure: a description with a double quote, a backslash and a line break is read back unchanged by `json.loads` |
| `test_money_has_two_places` | Pure: `Decimal("-120")` renders `-120.00`, `Decimal("0.50")` renders `0.50`, `Decimal("1250.00")` renders `1250.00` |

### 5.2 `test_statement_export_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_fixture_round_trips_through_the_import` | Import the fixture as "Fatura Cartão Exemplo, set/2026". Export it. `read_payload` the file bytes, then `import_statement` them as a new statement of the same user. The new statement has the same name, the same total `"11906.35"`, and the same 17 lines, compared as `(id, secao, data, descricao, valor as Decimal, categoria, duvida)`, with the `id` of the new statement's lines not compared. The two doubtful lines are still doubtful |
| `test_moved_line_is_exported_in_its_new_category` | Set line 10 ("Correios Demo", `DESPESA ADMINISTRATIVA`) to `OPERACIONAL` through the ORM. The file has `"descricao": "Correios Demo"` with `"categoria": "OPERACIONAL"`. The re-import keeps it there |
| `test_exact_cents_survive_the_round_trip` | A payload of "Loja Exemplo" `0.10` and "Loja Exemplo" `0.20` with total `0.30`. The file has `0.10` and `0.20`, and the re-import accepts the total exactly (a float reading would make the sum check fail) |
| `test_empty_or_untotalled_statement_is_409` | A statement inserted through the ORM with no lines, and one with `total_lanc_atuais` null and lines: both `409 statement_not_exportable`, with no file in the body |
| `test_sum_mismatch_is_409` | A statement whose one stored amount is changed through the ORM by R$ 0,01: `409 statement_not_exportable` |
| `test_other_users_statement_is_identical_to_missing` | A second user gets `404` for the first user's statement, with the same status, body bytes and headers as for a random uuid4, except `X-Request-Id`. The first user gets `200` |

## 6. Open questions

Each question has a recommendation. The owner is away, so these are delegated: the recommendation will be adopted (delegated: the owner is away; the recommendation will be adopted).

1. **A server endpoint or an export built in the browser.** *Recommended: the server endpoint of this spec (delegated: the owner is away; the recommendation will be adopted).* The file is the import's contract, and the server already owns its checks (BE-05) and the ownership rule (BE-10). A browser export would repeat the rules, and would export a view the browser built from the lines, not the stored shape. The alternative is an export built in the browser from BE-10's response. It needs no endpoint, but the round trip is then a promise of the frontend, not of the API.

2. **Money as JSON numbers.** *Recommended: JSON numbers with two places, written unquoted (3.3).* BE-05 accepts only JSON numbers, so the file must carry numbers for the import to read it. The usual rule of the API (money as a decimal string) does not hold for this file, and this spec says so on purpose. Changing BE-05 to accept strings would change an approved and merged contract, which is not this item's to do. The alternative is a string-money file plus a second import format, which is more code and a second door for statement data (BE-05 section 1 rules that out).

3. **A statement BE-05 could not store.** *Recommended: `409 statement_not_exportable` (delegated: the owner is away; the recommendation will be adopted).* A statement with no lines or no total is reachable only through the ORM or a later repair (BE-10 section 3.2 and BE-12 section 5 insert one). Exporting it would give a file that the import refuses, which breaks the round trip. The alternative is to export it anyway and let the import refuse it, which puts the failure in the wrong place.

4. **The filename.** *Recommended: the fixed literal `fatura.json` (delegated: the owner is away; the recommendation will be adopted).* The statement name holds a card and a month, and a name in a header is personal data that the logs and the headers must not carry. The id is not personal, but it adds nothing for the person who downloads the file. The alternative is `fatura-<short id>.json`, which lets two downloads be told apart on disk at the cost of an id in a header.

5. **What the file leaves out: the review state and the original category.** *Recommended: leave both out (delegated: the owner is away; the recommendation will be adopted).* The file has the BE-05 shape, which BE-05 accepts with no extra field, so `reviewed` and `moved_by_user` would be refused on the way back in. The accounting tools need the category, which is in the file. The alternative is to add these fields to the file and to BE-05 as optional, which changes BE-05's contract and is a later decision.

6. **The browser's handling of an error.** Not a question for this spec, a note for FE-13's spec: a plain `<a download>` saves a `401` or `503` body as `fatura.json`. FE-13 should fetch the file, check the status, and then save the blob (or show the JSON error). Nothing in this item changes.

### Gaps for the owner

- **The label in FE-13.** The story says the file has the category "Operacional". The file carries the code `OPERACIONAL`, the same as the import, because labels are BE-16's decision. The story's wording and the file differ until BE-16 says where the labels come from. This spec does not fix it.
- **`reviewed` in the file.** FE-13 does not say whether the reviewed state is exported. This spec says no (question 5). The owner should confirm it.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| The categories are seeded (10) | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted (delegated) |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production database, no deploy.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | BE-05 accepts money only as a JSON number: `as_decimal` refuses `str`, `bool` and `float`, and `read_payload` parses with `parse_float=Decimal` | *Verified*, `app/api/server/statements.py`, lines 77 to 82 and 142 to 150 | `test_rendered_export_passes_the_import_model`, `test_money_is_an_unquoted_number` |
| 2 | The fixture's "Correios Demo" is line 10, `DESPESA ADMINISTRATIVA`, `valor` 32.4 | *Verified*, `app/fixtures/statement-example-2026-09.json`, line 13 | Check 4 |
| 3 | `Statement.total_lanc_atuais` is nullable, and `transactions.section` is limited to the three English values | *Verified*, `app/api/server/db/models.py`, lines 99 and 121 | `test_empty_or_untotalled_statement_is_409` |
| 4 | `app_backend` can read `statements` and `transactions`: the reads of BE-10 and BE-12 run as that role in their merged `db` tests. The grants in migrations 0002 to 0005 were not re-read for this spec | *Verified* through the merged `db` tests of BE-10 and BE-12; the migrations are not re-read | Check 4 runs as `app_backend` |
| 5 | psycopg 3 returns `numeric(14,2)` as a `Decimal` that keeps its two places | *Assumed* (as BE-10 section 8, claim 8) | `test_exact_cents_survive_the_round_trip`; the formatting is `f"{value:.2f}"`, so a missing scale still prints two places |
| 6 | A plain `Response` with a bytes body and custom headers is sent unchanged by the middleware (the request log and the security headers of BE-32) | *Assumed* | `test_export_headers_are_fixed` |
| 7 | Every route of the app is covered by `test_access_routes.py` with a sample id in the path, so the new route needs no edit there | *Verified* by BE-12 section 8, claim 2, not re-read here | Check 1 |
| 8 | A statement of 500 lines fits in the 512 KiB that BE-05 accepts. The file is about 200 bytes a line, so about 100 KiB | *Assumed* from arithmetic on the fixture's line length | Check 1 (no test of the size itself) |

## 9. Notes for the implementer

- Build the body by hand, as section 3.3 says. Do not change the route to `JSONResponse`, `model_dump_json()` or `response.json()` in a test: each one turns money into a string or a float, and BE-05 then refuses the file.
- The round trip is a test, not a claim: `test_fixture_round_trips_through_the_import` and `test_rendered_export_passes_the_import_model` must pass before the PR.
- `SECTIONS_OUT` is built from BE-05's `SECTIONS`, so the two maps cannot drift.
- **Cross-item:** when BE-09 adds `card_name` and `card_last4` to the import, the export gets the same optional fields in the same change, or the round trip stays whole only for files without them. BE-14's verification then grows by one case in that item's spec, not here.
- **Cross-item:** BE-13 adds `moved_by_user` to the view, not to the file. The export does not change when BE-13 lands.

## Amendments before approval (2026-11-21)

- BE-09 is merged before this item (delegated order): the export includes `cartao_nome` and `cartao_final` when the statement has them, and omits them when null, so the round trip through BE-05 keeps them. A test exports the fixture (which carries the card) and re-imports it.
- A statement whose status is not `ready` is `409 statement_not_exportable`, as BE-07 makes non-ready statements empty.
