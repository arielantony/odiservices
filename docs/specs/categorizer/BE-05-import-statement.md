# Spec — BE-05 Import a statement from the extraction JSON

| | |
|---|---|
| **Backlog** | Feature: Categorizer › Statement upload and processing › BE-05 |
| **Story** | None. FE-03 (BE-03) and FE-04 (BE-06) come after it |
| **Depends on** | BE-24 (Done), BE-28 (Done), BE-29 (Done), BE-30 (Done) |
| **Spec status** | Approved (2026-11-10), with the recommended answers to section 6 |
| **Date** | 2026-11-10 |

## 1. Goal

The extraction of a card statement (the JSON that `ask_pdf.py` asks Claude
for: `total_lanc_atuais` and `lancamentos`) enters the portal through one
call, `POST /api/statements`. The call validates the JSON, checks that the
transactions add up to the printed total, and stores one `statements` row and
its `transactions` rows for the signed-in user, all or nothing.

This is the only door for statement data. BE-03 (upload and extraction on the
server) will call the same function with what Claude returns, so the checks
live in one place. Nothing here calls Anthropic or reads a PDF.

## 2. Scope

**In scope**

- `POST /api/statements` and the function behind it (`import_statement`).
- The validation of the payload and the sum check (3.2).
- The mapping from the extraction's Portuguese names to the English columns
  of BE-28 and BE-29 (3.3). It is done once, here.
- A handler that turns FastAPI's request validation errors into the portal's
  error format (3.5). Today no route has a body, so none exists.
- The canonical fixture `app/fixtures/statement-example-2026-09.json`, which
  `docs/TESTING_GUIDELINES.md` names but does not exist yet (3.6).
- Tests (section 5).

**Out of scope**

- Upload of the PDF, the call to Claude, `ANTHROPIC_API_KEY`: BE-03, BE-04.
- A processing status and a failure reason: BE-07. An import that fails stores
  nothing.
- Card name and last digits: BE-09. The category before a user move: BE-13.
- Reading a statement back, listing, changing, deleting: BE-10, BE-06, BE-11,
  BE-15.
- Any screen: FE-03 and later.

## 3. Design

### 3.1 The route

`POST /api/statements`, behind the Access check (BE-23) and `current_user`
(BE-24). The statement belongs to the person in the token, never to a user id
sent in the body.

Request body (JSON, at most 512 KiB):

```json
{
  "name": "Fatura Cartão Exemplo, set/2026",
  "total_lanc_atuais": 11906.35,
  "lancamentos": [
    {"id": 1, "secao": "compras", "data": "05/09", "descricao": "Distribuidora Exemplo Ltda",
     "valor": 1250.0, "categoria": "FORNECEDOR", "duvida": false}
  ]
}
```

The field names of `total_lanc_atuais` and `lancamentos` are exactly the
extraction's (`ask_pdf.py`, `SCHEMA`), so BE-03 can pass Claude's output with
`name` added and no translation (question 1). Unknown fields are refused,
as `additionalProperties: false` does in `SCHEMA`.

Response `201`, with `Cache-Control: no-store`. No description, and no value
that was not a count, a total or an id:

```json
{"id": "6f1c...-uuid", "name": "Fatura Cartão Exemplo, set/2026",
 "total": "11906.35", "transaction_count": 17, "doubtful_count": 2}
```

Money in the API is a **decimal string** (`"11906.35"`), never a float, in
responses. The request accepts JSON numbers, as the extraction produces them,
and reads them as decimals, not as binary floats.

### 3.2 Validation, in this order

All of it before the first insert.

| # | Rule | Failure |
|---|---|---|
| 1 | Body at most 512 KiB (`Content-Length`) | `413 payload_too_large` |
| 2 | The shape of 3.1: required fields, types, no unknown field | `422 invalid_statement` |
| 3 | `name`: 1 to 120 characters after trimming | `422 invalid_statement` |
| 4 | 1 to 500 transactions | `422 invalid_statement` |
| 5 | `id`: integer, at least 1, unique in the payload | `422 invalid_statement` |
| 6 | `secao` one of `compras`, `internacional`, `produtos`; `data` and `descricao` not empty after trimming (`descricao` at most 300 characters) | `422 invalid_statement` |
| 7 | `valor` and `total_lanc_atuais`: at most 2 decimal places, absolute value below 10^12 | `422 invalid_statement` |
| 8 | `categoria` is a `portal.categories.code` (read from the table, not from a list in code) | `422 unknown_category` |
| 9 | The sum of `valor`, in decimals, equals `total_lanc_atuais` to the cent | `422 total_mismatch` |

The ids may have gaps (question 3). Negative values (refunds) are accepted in
any category; `ask_pdf.py` only warns about refunds outside `OUTROS`, and a
warning does not stop an import.

The failure messages (pt-BR) never carry a value from the payload: no
description, no amount, no category text. `total_mismatch` does not even say
the two totals. Details go nowhere: the log carries counts only.

### 3.3 What is stored

One database transaction. If anything fails, nothing is stored.

| Payload | Column |
|---|---|
| `name` (trimmed) | `statements.name` |
| `total_lanc_atuais` | `statements.total_lanc_atuais` |
| the token's user | `statements.user_id` |
| `id` | `transactions.item_number` |
| `secao`: `compras`, `internacional`, `produtos` | `transactions.section`: `purchases`, `international`, `products` |
| `data` | `transactions.printed_date` (text, as printed) |
| `descricao` | `transactions.description` |
| `valor` | `transactions.amount` |
| `categoria` | `transactions.category_code` |
| `duvida` | `transactions.doubtful` |

`reviewed` stays `false`. The rows are inserted in bulk (one statement, one
insert for all the transactions). Sending the same statement twice stores two
(question 4).

### 3.4 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 413 | `payload_too_large` | `A fatura enviada é grande demais.` |
| 422 | `invalid_statement` | `Os dados da fatura são inválidos.` |
| 422 | `unknown_category` | `A fatura tem uma categoria desconhecida.` |
| 422 | `total_mismatch` | `A soma dos lançamentos não confere com o total da fatura.` |
| 503 | `database_unavailable` | from BE-24, unchanged |

### 3.5 Request validation errors

FastAPI answers a body that fails validation with `{"detail": [...]}`, which
repeats the offending values and breaks the format above. This item registers
a handler for `RequestValidationError` that answers `422 invalid_statement`
with the fixed message. It applies to every route, and no route has a body
today, so it changes nothing that exists. The handler never echoes the input.

### 3.6 The canonical fixture

`app/fixtures/statement-example-2026-09.json` is the extraction of "Fatura
Cartão Exemplo, set/2026", in the shape of 3.1 without `name`: 17
transactions, total `11906.35`, two with `duvida: true` ("Software Gestão
Teste" in `OPERACIONAL`, "Compra Não Identificada" in `OUTROS`). It is built
from the `cards` of `docs/prototypes/portal/v3-generate.py`, so the prototype,
the stories and the tests describe the same data.

- Category per lane, as codes: `FORNECEDOR`, `OPERACIONAL`,
  `MARKETING/COMERCIAL`, `INVESTIMENTO`, `DESPESA ADMINISTRATIVA`,
  `FOLHA DE PAGAMENTO`, `CUSTO DO CARRO`, `DESPESAS FINANCEIRAS`,
  `OUTROS` (the lane "Pessoa física", `PESSOA FISICA`, is empty).
- `data` is `05/09` on every line.
- `secao`: `compras` everywhere, except "IOF Compra Exterior"
  (`internacional`) and "Tarifa Bancária Exemplo" (`produtos`), so the three
  values are covered.
- "Papelaria Fictícia" was moved by the user in the prototype. That is board
  state (BE-13), not extraction, so the fixture has it in `FORNECEDOR` like
  any other line.
- Ids are 1 to 17 in the order of the prototype's lanes.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | New: the Pydantic models of the payload (`extra="forbid"`), `import_statement(session, user, payload)`, the section map |
| `app/api/server/routes/statements.py` | New: `POST /api/statements`, size check |
| `app/api/server/main.py` | Register the router and the `RequestValidationError` handler |
| `app/fixtures/statement-example-2026-09.json` | New: 3.6 |
| `docs/TESTING_GUIDELINES.md` | The fixture's description gains "the extraction shape, without `name`" |
| `docs/BACKEND_GUIDELINES.md` | Layout and Errors: the new module and the handler |
| `app/api/tests/test_statement_payload.py`, `test_statements_import.py`, `test_statements_import_db.py` | New: section 5 |
| `docs/BACKLOG.md` | BE-05 to In progress, then the PR link |

No migration, no new setting, no new dependency (Pydantic ships with
FastAPI).

### 3.8 Steps

One step, about 450 lines with the tests and the fixture. Branch
`feat/be-05-import-statement`, from `origin/main`, PR to `main`. The estimate
is the tightest part of the spec: if the code passes 500 lines, I stop and
propose a split at the seam between the validation (3.2, 3.5, 3.6) and the
persistence (3.3).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no production check: no migration and no deploy.

| # | Check | Expected |
|---|---|---|
| 1 | `make test-api` | All pass, `db` tests deselected |
| 2 | `make db-up && make test-db` | All pass, including the new `db` tests |
| 3 | The canonical fixture sums to its total: `python3 -c "import json,decimal as d;f=json.load(open('fixtures/statement-example-2026-09.json'));print(sum(d.Decimal(str(l['valor'])) for l in f['lancamentos']),f['total_lanc_atuais'],len(f['lancamentos']))"` from `app/` | `11906.35 11906.35 17` |
| 4 | Import the fixture through the app against the local database (`test_import_canonical_fixture_stores_17_rows`) and `select count(*) from portal.transactions where doubtful;` on that statement | The test passes and the count is `2` |
| 5 | `test_total_mismatch_stores_nothing`: the fixture with one amount changed by R$ 0,01 | `422 total_mismatch`, and `select count(*)` on `statements` and `transactions` is unchanged |
| 6 | `test_error_bodies_carry_no_payload_value` | Passes: no description or amount in any error body |

## 5. Tests

Fictitious data only: the canonical fixture, changed in memory for the
failure cases. The Access check and the user row use the helpers of
`tests/access_helpers.py` and `test_users_resolution_db.py`, with the
verifier faked, as in BE-24. No call leaves the machine.

`test_statement_payload.py` (no database):

- `test_fixture_validates`: the canonical fixture passes the payload model.
- `test_unknown_field_is_refused`: a top-level and a per-line extra field.
- `test_duplicate_ids_are_refused`, `test_id_zero_is_refused`,
  `test_gaps_in_ids_are_accepted`.
- `test_section_values`: the three accepted, another refused.
- `test_empty_description_and_date_are_refused`, `test_long_description_is_refused`.
- `test_three_decimal_places_are_refused`, `test_huge_amount_is_refused`.
- `test_zero_or_501_transactions_are_refused`.
- `test_amounts_are_read_as_decimals`: `0.1 + 0.2` style lines add to the
  exact total.

`test_statements_import.py` (app with a fake session, no database):

- `test_requires_access`: no token, `401`, nothing stored.
- `test_validation_error_uses_the_portal_format`: the body of a refused
  request is `{"error": {"code": "invalid_statement", "message": ...}}`.
- `test_error_bodies_carry_no_payload_value`: a description, an amount and a
  category text planted in a bad payload do not appear in the body.
- `test_oversized_body_is_413`.

`test_statements_import_db.py` (marker `db`, local Postgres, as `app_backend`):

- `test_import_canonical_fixture_stores_17_rows`: one statement owned by the
  token's user, 17 transactions, total `11906.35`, `reviewed` false on all,
  two `doubtful`.
- `test_section_and_category_are_mapped`: `compras` becomes `purchases`,
  `PESSOA FISICA` style codes survive, the amounts keep their cents.
- `test_unknown_category_stores_nothing`.
- `test_total_mismatch_stores_nothing`.
- `test_failure_midway_rolls_back`: a duplicate `item_number` forced past the
  payload check leaves no statement row.
- `test_statement_belongs_to_the_token_user`: a `user_id` in the body is
  refused as an unknown field; two users each get their own row.
- `test_same_statement_twice_stores_two`.
- `test_response_has_counts_and_no_description`.

## 6. Open questions

Answered by the owner on 2026-11-10: 1 follows the recommendation, 2 refuse,
3 accept, 4 yes (store two). Each question below keeps its recommendation
for the record.

1. **Names in the request body.** Keep the extraction's own names
   (`total_lanc_atuais`, `lancamentos`, `secao`, `valor`, ...), or define
   English names and make BE-03 translate? *Recommended:* the extraction's
   names. The item is "import the extraction JSON", `ask_pdf.py`'s schema is
   the contract Claude already fills, and the English mapping happens once,
   inside the import (3.3). Every response and table stays in English
   (owner's rule of 2026-11-10).
2. **A total that does not match.** Refuse the import (`422`), or store it
   and flag it? *Recommended:* refuse. There is no flag column and no status
   until BE-07. BE-03 will turn the refusal into "Falhou: ..." with a retry
   (BE-08), and nobody sees numbers that do not add up.
3. **Ids with gaps.** `ask_pdf.py` warns about gaps in `1..N` but continues.
   Refuse them or accept? *Recommended:* accept. The database needs only
   unique ids at least 1, and a gap is not a wrong total.
4. **The same statement imported twice.** Store two, or refuse by name?
   *Recommended:* store two. There is no natural key (two cards can share a
   month's name), BE-15 deletes the extra one, and a name check would block a
   legitimate re-import after a fix.


## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| Local Postgres up | agent | `make db-up && make db-current` from `app/` | `0005 (head)` |
| `statements`, `transactions` and `categories` exist locally | agent | `psql` as `odiservices`: `select count(*) from portal.categories;` | `10` |
| The Access verifier can be faked in tests | agent | `make test-api -k users_resolution` | Passes |
| OrbStack running | owner | `docker info` | Prints the server version |

The statements and transactions tables are also in Supabase (BE-28, BE-29),
but this item never touches it: the route is tried against the local database
only. Approvals: none beyond the PR.

## 8. Assumptions to verify

| # | Claim | Status | Check |
|---|---|---|---|
| 1 | Pydantic reads a JSON number such as `89.9` as `Decimal("89.9")`, not as the binary float | **assumed** | `test_amounts_are_read_as_decimals`, first test written |
| 2 | `RequestValidationError` can be handled app-wide with `add_exception_handler` and the handler never sees a response already built by the middleware | **assumed** | `test_validation_error_uses_the_portal_format` |
| 3 | Reading `Content-Length` is enough to bound the body in this stack (the nginx `web` image also limits it) | **assumed** | `test_oversized_body_is_413`; a chunked body without a length is a gap, recorded here, closed when BE-03 sets the upload limit |
| 4 | `app_backend` can insert into `statements` and `transactions` through the default privileges of `0001` | verified (BE-28, BE-29 `db` tests) | Re-run by the `db` tests |
| 5 | A ceiling of 500 lines and 512 KiB covers a real statement (the real one has about 20 to 60 lines) | **assumed** | The owner confirms with a statement of theirs once BE-03 exists (*Pending validation*, no data recorded) |
