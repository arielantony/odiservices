# Spec — BE-09 Store the card name and last digits of each statement

| | |
|---|---|
| **Backlog** | Platform/Feature: Categorizer › BE-09 (the backlog row lists BE-28 only; this spec also depends on BE-05 and BE-10 because it changes their contracts, see 3.1 and 3.4) |
| **Story** | `docs/stories/board/FE-06-statement-summary.feature` (the ticket shows "Cartão Exemplo final 0000") |
| **Depends on** | BE-28 (Done), BE-05 (Done), BE-10 (Done). BE-06 is optional: see 3.7 for both orders |
| **Spec status** | Approved (2026-11-21). The owner delegated every decision of the open questions section and the recommendations were adopted |
| **Date** | 2026-11-21 |

## 1. Goal

Each statement records which card it came from: the card's name as printed on
the statement ("Cartão Exemplo") and its last four digits ("0000"). The import
(BE-05) accepts both as optional fields, the table (`portal.statements`) stores
them through migration `0007`, and the read (BE-10) returns them, so FE-06 can
show "Cartão Exemplo final 0000" in the statement ticket. Both fields are
optional: a statement without them stays valid and shows no card line.

## 2. Scope

**In scope**

- Migration `0007_statement_card`: two nullable columns on `portal.statements`,
  with their check constraints, and a downgrade.
- The ORM model `Statement` (`server/db/models.py`): the two columns and their
  constraints, kept identical to the migration (drift test).
- The import payload of `POST /api/statements` (BE-05): two optional keys, and
  their storage in `import_statement`.
- The read `GET /api/statements/{statement_id}` (BE-10): two response fields.
- The canonical fixture: the two keys added (3.5).
- Tests (section 5).

**Out of scope**

- The extraction that fills the keys from a PDF: `ask_pdf.py` SCHEMA and
  `prompt-pdf.md`. They belong to BE-03, which moves `ask_pdf.py` into
  `app/api/` (see open question 4).
- The list fields (`card_name`, `card_last4` on `GET /api/statements` items):
  BE-06, or BE-09 later if BE-06 merges first (3.7).
- Editing the card of a statement after the import: no route exists and none
  is planned. A wrong card is removed with the statement (BE-15) and imported
  again.
- Any screen: FE-06 shows the card line. The UI string is FE-06's.
- The 201 response of the import stays as BE-05 defines it. The card is read
  through BE-10.

## 3. Design

### 3.1 The import payload (BE-05, spec 3.1 and 3.2)

Two optional top-level keys join `name`, `total_lanc_atuais` and
`lancamentos`. Their names are Portuguese, like the extraction's
(`cartao_nome`, `cartao_final`), and the model keeps `extra="forbid"`.

```json
{
  "name": "Fatura Cartão Exemplo, set/2026",
  "cartao_nome": "Cartão Exemplo",
  "cartao_final": "0000",
  "total_lanc_atuais": 11906.35,
  "lancamentos": [ ... ]
}
```

| Key | Type | Rule | Stored in |
|---|---|---|---|
| `cartao_nome` | string, or absent or `null` | After trimming, 1 to 60 characters. An empty or blank string is refused | `statements.card_name` |
| `cartao_final` | string, or absent or `null` | Exactly four ASCII digits `0-9`, as a **string**, so leading zeros survive. A JSON number (`0`, `1234`) is refused | `statements.card_last4` |

- Absent and `null` mean the same: the column is NULL.
- Both rules sit in the same `422 invalid_statement` as the other shape errors
  (BE-05, rule 2 and 3). The messages do not echo the value.
- Implementation: in `StatementPayload` (`server/statements.py`) add
  `cartao_nome: Annotated[str | None, StringConstraints(strip_whitespace=True,
  min_length=1, max_length=60)] = None` and `cartao_final: Annotated[str | None,
  StringConstraints(pattern=r"^[0-9]{4}$")] = None`. The model is strict, so a
  number is not coerced to a string. The pattern uses `[0-9]`, not `\d`, which
  also matches other Unicode digits.
- `import_statement` passes both values to the `Statement(...)` it creates.
  Nothing else in the transaction changes.
- The 201 response is unchanged (BE-05 spec 3.1): no card value in it.

### 3.2 The table (migration `0007`)

`down_revision` is `0006` if BE-13 is merged when this PR merges, otherwise
`0005` (see 3.7). The revision id is `0007`, as reserved in the preamble.

The SQL the migration produces, in effect:

```text
ALTER TABLE portal.statements ADD COLUMN card_name text NULL;
ALTER TABLE portal.statements ADD COLUMN card_last4 char(4) NULL;
ALTER TABLE portal.statements ADD CONSTRAINT ck_statements_card_name_not_empty CHECK (card_name <> '');
ALTER TABLE portal.statements ADD CONSTRAINT ck_statements_card_last4_digits CHECK (card_last4 ~ '^[0-9]{4}$');
```

Written with Alembic `op.add_column(..., schema="portal")` and
`op.create_check_constraint(op.f(...), ...)`, following `0004_statements.py`.

- `card_name` `text`, nullable. A CHECK that is not empty, and NULL passes a
  CHECK, so NULL stays allowed.
- `card_last4` `char(4)`, nullable. The check takes exactly four digits. NULL
  passes it.
- No index, no backfill, no default. Existing rows get NULL, which is correct:
  they were imported without a card.
- Access: no grant. `app_backend` reads and writes the table through the
  default privileges of `0001`, and the new columns come with the table
  (3.8, assumption 3). RLS is unchanged.
- Downgrade: drop both constraints, then both columns. Tested locally
  (section 5), never run in production by the agent.
- Additive and backward compatible: an old server that does not know the
  columns still inserts and reads its own columns, and NULL is the default.
  The deploy order is in section 4, *After merge*: the migration first, then
  the code that names the columns.

### 3.3 The model (`server/db/models.py`)

```python
class Statement(Base):
    __table_args__ = (
        CheckConstraint("name <> ''", name="name_not_empty"),
        CheckConstraint("card_name <> ''", name="card_name_not_empty"),
        CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name="card_last4_digits"),
        Index("ix_statements_user_id_created_at", "user_id", text("created_at DESC")),
    )
    ...
    card_name: Mapped[str | None] = mapped_column(Text)
    card_last4: Mapped[str | None] = mapped_column(CHAR(4))
```

- `__repr__` is unchanged: it shows the id only, and the card name is as
  private as the statement name.
- The constraint names match the migration's `op.f(...)` names, so the drift
  test (BE-31) sees no difference. If it reports one, the migration or the
  model is wrong, not the test.

### 3.4 The read (BE-10, spec 3.2 amended)

`StatementView` (`server/statements.py`) gains `card_name: str | None` and
`card_last4: str | None`, and `read_statement` fills them from the row. The
header becomes:

```json
{
  "id": "...", "name": "Fatura Cartão Exemplo, set/2026",
  "card_name": "Cartão Exemplo", "card_last4": "0000",
  "total": "11906.35", "created_at": "...", ...
}
```

- Both are returned as stored: `null` when absent, the string otherwise (the
  four digits as a string, `"0000"`).
- The change is additive. BE-10's contract (amended here, in the same PR as
  this item): a new `card_name` and `card_last4` in the header.
- BE-10's log rule is unchanged: the route template is logged, never the card
  name or the digits (3.5).

### 3.5 Logging and privacy

- Neither the card name nor the last digits is logged. The request log (BE-21)
  records the route only; the import logs counts and status, as BE-05 says.
- Errors never carry them: the refusal messages of BE-05 (3.4) do not echo a
  value, and that covers `cartao_nome` and `cartao_final` too.
- The last four digits are not the card number, but they identify a card for
  its owner, so they are treated like the statement name: stored, returned
  to the owner, never logged.

### 3.6 The canonical fixture

`app/fixtures/statement-example-2026-09.json` gains the two keys with the
fictitious values:

```json
"cartao_nome": "Cartão Exemplo",
"cartao_final": "0000",
```

- Fictitious (the "Exemplo" name and the round "0000"), and the values FE-06's
  story already shows, so the prototype and the story describe the same card.
- The sum check and the 17 lines are unchanged. `test_fixture_validates`
  (BE-05) now also covers the two keys.
- `docs/TESTING_GUIDELINES.md` says a fixture change updates the prototype
  generator (`docs/prototypes/portal/v3-generate.py`, `cards`) in the same
  change. The generator is to carry the same two values; if it does not, the
  PR adds them there too (assumption 5).
- `docs/TESTING_GUIDELINES.md` describes the fixture as "the extraction shape,
  without `name`". After this item it reads "without `name`; the card keys are
  optional".

### 3.7 Order with BE-06 and BE-13

BE-06 (the list) is Draft and BE-13 (`0006`) is Draft. The two cases:

- **BE-06 merged first.** Its item fields are `id, name, total, created_at,
  transaction_count, pending_review_count`. BE-09 then adds `card_name` and
  `card_last4` to the list item, in the same serializer as the header, and one
  test in BE-06's file asserts the two keys. The keyset cursor is unaffected
  (it uses `created_at` and `id`).
- **BE-09 merged first.** BE-06's spec, when it is written, lists `card_name`
  and `card_last4` among the item fields from the start, and the BE-06 item
  does not need a second change. Until BE-06 lands, the list has no card, which
  is harmless: the board (BE-10) is what FE-06 reads.

Either way the change is additive. Neither order touches the other's files
beyond the serializer and its test.

Migration order: `0006` (BE-13) and `0007` (BE-09) both branch from `0005`.
Whichever merges second rebases its `down_revision` in its own PR, to the head
at that time: if BE-13 is merged first, `0007.down_revision = "0006"`; if BE-09
is merged first, BE-13 sets its `down_revision` to `"0007"`. The PR states the
head it was built on. Two heads are a failing check (section 4, check 3).

### 3.8 Steps

One step, about 250 to 300 changed lines with the tests and the fixture. Branch
`feat/be-09-card-fields`, from `origin/main`, PR to `main`. If it passes 500
lines the step is split at the seam between the migration and model (first) and
the payload and read (second).

### 3.9 Files

| File | Change |
|---|---|
| `app/api/migrations/versions/0007_statement_card.py` | New: two columns, two check constraints, downgrade (3.2) |
| `app/api/server/db/models.py` | `Statement`: the two columns and their constraints (3.3) |
| `app/api/server/statements.py` | `StatementPayload` gets the two optional keys; `import_statement` stores them; `StatementView` gets the two fields; `read_statement` fills them |
| `app/fixtures/statement-example-2026-09.json` | The two keys (3.6) |
| `docs/prototypes/portal/v3-generate.py` | Only if its `cards` lacks "Cartão Exemplo" / "0000" (3.6) |
| `docs/TESTING_GUIDELINES.md` | The fixture description (3.6) |
| `app/api/tests/test_statement_payload.py` | New cases (section 5) |
| `app/api/tests/test_statements_import_db.py` | New cases (section 5) |
| `app/api/tests/test_statement_read.py` | Log test plants a card name and digits (section 5) |
| `app/api/tests/test_statement_read_db.py` | Canonical read checks the two fields |
| `app/api/tests/test_statement_model.py` | Column types and repr (section 5) |
| `app/api/tests/test_statement_card_migration_db.py` | New: migration and constraints, marker `db` (section 5) |
| `docs/specs/categorizer/BE-10-get-statement.md` | Amendment note for the header fields (3.4), in the same PR. Not BACKLOG.md, which the owner updates |

`ask_pdf.py`, `prompt-pdf.md` and `app/api/server/routes/statements.py` are not
changed (no new route, and the extraction is BE-03's).

## 4. Verification

Checks that run when the item merges, with the local Postgres (`make db-up`).
Run from `app/` unless stated.

| # | Check | Expected |
|---|---|---|
| 1 | `make test-api` | All pass, `db` tests deselected |
| 2 | `make db-up && make test-db` | All pass, including `test_statement_card_migration_db.py` and the drift test (BE-31) |
| 3 | `make db-upgrade && make db-current` | The head printed is `0007 (head)` on a branch built on `0005`, or `0007 (head)` on one built on `0006` (3.7). A second `make db-upgrade` changes nothing |
| 4 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select column_name\|\|':'\|\|data_type\|\|':'\|\|is_nullable from information_schema.columns where table_schema='portal' and table_name='statements' and column_name like 'card_%' order by column_name"` | Two lines: `card_last4:character:YES`, `card_name:text:YES` |
| 5 | `cd app/api && .venv/bin/python -m pytest -m db tests/test_statement_card_migration_db.py -v` | All pass, including the refusals of a bad `card_last4` and an empty `card_name` (section 5) |
| 6 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_payload.py tests/test_statement_read.py tests/test_statement_model.py -v` | All pass, the new cases included |
| 7 | `cd app && make db-downgrade`, then the query of check 4, then `make db-upgrade` | An empty result, then `0007 (head)` again |
| 8 | `cd app && python3 -c "import json,decimal as d;f=json.load(open('fixtures/statement-example-2026-09.json'));print(f['cartao_nome'],f['cartao_final'],sum(d.Decimal(str(l['valor'])) for l in f['lancamentos']),f['total_lanc_atuais'])"` | `Cartão Exemplo 0000 11906.35 11906.35` |
| 9 | `test_fixture_card_keys_import` (section 5) imports the fixture and reads it back through `GET`, as `app_backend` | `card_name` `Cartão Exemplo`, `card_last4` `0000`, `total` `11906.35` |

### After merge (deploy)

Run by the owner, from `main`, against Supabase. The agent never holds the
credential and never connects to Supabase. The item stays *In progress* until
these pass, and the Done PR records the result.

1. Backup: `scripts/db-backup.sh`.
2. Plan: `make db-sql FROM=<production head>`, where the production head is
   what `make db-current` shows against Supabase (`0005 (head)` if BE-13 is not
   applied, `0006 (head)` if it is). The owner reads the SQL: it adds the two
   columns and the two constraints to `portal.statements`, nothing else, no
   password, no data. The owner says "apply".
3. Apply: `make db-upgrade`, then `make db-current` prints `0007 (head)`. A
   second `make db-upgrade` changes nothing.
4. Read back, as the owner in `psql`:
   `select column_name, data_type from information_schema.columns where table_schema='portal' and table_name='statements' and column_name like 'card_%' order by column_name;` shows `card_last4 | character` and `card_name | text`.
   `select count(*) from portal.statements;` is unchanged from before the step.
5. Deploy the code **after** step 3. The BE-10 read names the new columns, so
   a server that runs this code before `0007` fails its reads. The migration
   first, then the deploy.

## 5. Tests

Fictitious data only: the canonical fixture, its card keys "Cartão Exemplo" and
"0000", and in the failure cases a changed copy made in memory. Planted values
for the log test are "Cartão Sigilo Exemplo" and "9876", which are fictitious.
The db tests use the BE-31 fixtures, the Access helpers and the BE-24 user
pattern (`tests/access_helpers.py`), with the verifier faked. No call leaves the
machine.

`test_statement_payload.py` (no database)

| Test | Asserts |
|---|---|
| `test_card_keys_are_optional` | A payload without them validates, and both attributes are `None` |
| `test_null_card_keys_are_accepted` | `cartao_nome: null` and `cartao_final: null` validate as absent |
| `test_card_last4_must_be_four_digits` | `"0000"` and `"0123"` pass; `"000"`, `"00000"`, `"00a0"`, `"0000 "` and the number `0` are refused |
| `test_card_name_bounds` | 60 characters pass, 61 is refused, `"   "` and `""` are refused, surrounding spaces are trimmed |
| `test_fixture_validates` (BE-05, extended) | The fixture with the two keys passes the model |

`test_statements_import_db.py` (marker `db`, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_card_fields_are_stored` | `card_name` `Cartão Exemplo` and `card_last4` `0000` stored on the statement row |
| `test_card_last4_keeps_leading_zeros` | `"0123"` is read back as `"0123"` |
| `test_card_fields_absent_store_null` | Without the keys, both columns are NULL and the import still returns 201 |
| `test_fixture_card_keys_import` | Imports the fixture; the 201 has no card value; the row has the two values |
| `test_card_refusal_stores_nothing` | A `cartao_final` of `"00A0"` gives `422 invalid_statement` and no statement row is written |

`test_statement_card_migration_db.py` (marker `db`)

| Test | Asserts |
|---|---|
| `test_card_columns_types_and_nullability` | `card_name` is text and nullable, `card_last4` is character(4) and nullable |
| `test_card_last4_rejects_non_digits` | An insert of `card_last4` `"00A0"` raises `IntegrityError` naming `ck_statements_card_last4_digits` |
| `test_card_last4_rejects_wrong_length` | `"000"` and `"00000"` raise the same constraint |
| `test_card_name_rejects_empty` | `card_name` `""` raises `IntegrityError` on `ck_statements_card_name_not_empty` |
| `test_null_card_fields_are_allowed` | Both NULL inserts succeed |
| `test_downgrade_removes_card_columns` | `downgrade 0006` (or `0005`, per 3.7) drops both columns; `upgrade head` restores them |
| `test_app_role_reads_and_writes_card_columns` | As `app_backend`, insert and select with the card columns work |
| `test_models_match_migrations` | The BE-31 drift test reports no difference for the two columns and constraints |

`test_statement_model.py` (no database), extended

| Test | Asserts |
|---|---|
| `test_card_columns_are_declared` | `card_name` is `Text` nullable, `card_last4` is `CHAR(4)` nullable |
| `test_repr_does_not_show_card` | `repr` shows the id only, not the card name or the digits |

`test_statement_read.py` and `test_statement_read_db.py` (BE-10, extended)

| Test | Asserts |
|---|---|
| `test_read_logs_carry_no_card` (in `test_statement_read.py`) | With a statement planted with card name "Cartão Sigilo Exemplo" and digits "9876", the captured log holds neither value. The owner's body may carry them (3.4), so the test checks only the log |
| `test_get_canonical_statement_in_order` (extended) | `card_name` `"Cartão Exemplo"` and `card_last4` `"0000"` on the header |
| `test_statement_without_card_reads_null` (new, db) | A statement imported without the keys reads `card_name: null` and `card_last4: null` |

## 6. Open questions

1. **The key names and their shape.** Flat top-level keys `cartao_nome` and
   `cartao_final`, or one nested object `cartao: {nome, final}`?
   *Recommended:* flat. The extraction is flat (`total_lanc_atuais`,
   `lancamentos`), and one more top-level key is the smallest change to the
   payload. (delegated: the owner is away; the recommendation will be adopted)
2. **Type of the last digits.** String (`"0000"`) or integer (`0`)?
   *Recommended:* string. An integer loses leading zeros, and `"0000"` must come
   back as `"0000"`. The pattern check keeps it to four digits. (delegated: the
   owner is away; the recommendation will be adopted)
3. **Required or optional.** *Recommended:* optional, with `null` allowed. A
   statement can be imported without a card (older statements, a CLI run
   without the new key), and the column is nullable in migration `0007`.
   (delegated: the owner is away; the recommendation will be adopted)
4. **Who makes the extraction return the fields.** `ask_pdf.py`'s SCHEMA has
   `additionalProperties: false` and no card property, so today Claude does not
   return them. *Recommended:* BE-03 adds `cartao_nome` and `cartao_final` as
   optional properties of the SCHEMA and an instruction to `prompt-pdf.md`, in
   the PR that moves `ask_pdf.py` into `app/api/`. BE-09 stays out of
   `ask_pdf.py`. Until BE-03, statements imported from the CLI have no card, and
   FE-06 shows no card line. (delegated: the owner is away; the recommendation
   will be adopted)
5. **Fixture and prototype generator.** *Recommended:* add the two keys to the
   fixture, and make `v3-generate.py` carry the same values if it does not
   already (3.6). (delegated: the owner is away; the recommendation will be
   adopted)
6. **Card name length.** *Recommended:* 1 to 60 characters after trimming, a
   limit well above the printed card label and well below the statement name's
   120. (delegated: the owner is away; the recommendation will be adopted)
7. **Should the 201 response echo the card?** *Recommended:* no. BE-05's 201
   carries no value but the name, and the card is read through BE-10.
   (delegated: the owner is away; the recommendation will be adopted)

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-05 merged: `POST /api/statements` exists | Agent | `cd app/api && grep -n 'post("/api/statements"' server/routes/statements.py` | One line |
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| Local Postgres at the head the branch was built on | Agent | `cd app && make db-up && make db-current` | `0005 (head)`, or `0006 (head)` if BE-13 is merged first (3.7) |
| The categories are seeded (the import checks them) | Agent | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| The fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation |
| Supabase head for the after-merge step | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-current` | `0005 (head)` or `0006 (head)`, run by the owner only |

**Packages.** None. `CHAR` and `CheckConstraint` come from SQLAlchemy, already pinned.

**Actions that need the owner's explicit OK.** Applying `0007` to Supabase
(section 4, *After merge*): the owner reads the SQL and says "apply". No other
production action.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | The payload model is `extra="forbid"` and `strict=True`, so the two new keys must be declared or they are refused | *Verified*, `server/statements.py` (`StatementPayload`) | `test_card_keys_are_optional` and `test_fixture_validates` |
| 2 | A CHECK constraint passes when the column is NULL, so the nullable card columns keep NULL allowed | *Assumed* (standard SQL behavior) | `test_null_card_fields_are_allowed` |
| 3 | `ALTER TABLE ... ADD COLUMN` on a nullable column with no default adds the column without rewriting the table, and `app_backend` needs no column `GRANT` (the table grant from the default privileges covers it) | *Assumed* from the default privileges of `0001`, as BE-28 assumption 4 | `test_app_role_reads_and_writes_card_columns` |
| 4 | Alembic's drift test (BE-31) compares CHECK constraints by name and sees the `card_last4` regular expression as a difference only if the two sides differ | *Assumed* | `test_models_match_migrations`; if it reports a difference on the expression text, the model and migration are aligned to the same text |
| 5 | `docs/prototypes/portal/v3-generate.py` `cards` carries the card name and digits | *Assumed* from FE-06's story (`Cartão Exemplo final 0000`); not read in this spec | Step 1 of the item: read the generator; add the values if absent (3.6) |
| 6 | `migration_files` and `migration_guards` tests (BE-31) require a downgrade and a `revision` naming pattern, which `0007` follows | *Assumed*, file names of `app/api/tests/` only; not read | `make test-api` in step 1 |
| 7 | psycopg 3 returns `char(4)` as `str` of length 4, and "0000" is returned without padding changes | *Assumed* | `test_card_last4_keeps_leading_zeros` |

## 9. Notes from the implementation

To be filled in when the item is built.
