# Spec — BE-29 Create the `transactions` table

| | |
|---|---|
| **Backlog** | Platform › Database › BE-29 |
| **Depends on** | BE-28 (Done), BE-30 (Done) |
| **Spec status** | Approved (2026-11-10), with the recommended answers to section 6 |
| **Date** | 2026-11-10 |

## 1. Goal

Each line of a card statement (a lançamento) is stored as one row of
`portal.transactions`. A transaction belongs to a statement (BE-28) and has a
category from the fixed set (BE-30). This item creates the table and the
model. It creates no row and no code that reads or writes one: importing the
extraction is BE-05, the board is BE-10 and BE-11.

**Column names are in English** (owner, 2026-11-10), even where the
extraction JSON of `ask_pdf.py` uses Portuguese. The import (BE-05) maps the
names; the table does not copy them.

## 2. Scope

**In scope**

- The table `portal.transactions` and its migration `0005_transactions`.
- The ORM model `Transaction` in `server/db/models.py`.
- Tests against the local Postgres (section 5).

**Out of scope**

- Creating transactions from the extraction, and checking that their sum
  equals `statements.total_lanc_atuais`: BE-05.
- The category before the user changed it: BE-13 adds that column.
- Routes to read or change a transaction: BE-10, BE-11, BE-12.
- Deleting a statement through the API: BE-15. This item only decides what the
  database does with the transactions when a statement row is deleted (3.1).

## 3. Design

### 3.1 The columns

| Column | Type | Rules |
|---|---|---|
| `id` | `uuid` | Primary key. Default `gen_random_uuid()`; the model also sets `default=uuid.uuid4` |
| `statement_id` | `uuid` | Not null. Foreign key to `portal.statements(id)`, `ON DELETE CASCADE` (question 1) |
| `item_number` | `integer` | Not null, at least 1. The line's number within the statement (`id` in the extraction JSON). Unique with `statement_id` |
| `section` | `text` | Not null. One of `purchases`, `international`, `products` (check constraint). The extraction's `secao`: `compras`, `internacional`, `produtos` (question 2) |
| `printed_date` | `text` | Not null, not empty. The date as the statement prints it, `dd/mm` (question 3) |
| `description` | `text` | Not null, not empty. The merchant text as printed |
| `amount` | `numeric(14,2)` | Not null. BRL. A refund or credit is negative, so there is no sign check |
| `category_code` | `text` | Not null. Foreign key to `portal.categories(code)`, `ON DELETE RESTRICT` (BE-30) |
| `doubtful` | `boolean` | Not null, default `false`. The classifier was unsure (the extraction's `duvida`) |
| `reviewed` | `boolean` | Not null, default `false`. A person confirmed or changed it (today `revisado` in the board's localStorage) |
| `created_at` | `timestamptz` | Not null, default `now()` |
| `updated_at` | `timestamptz` | Not null, default `now()`. The model sets `onupdate=func.now()`. No trigger, as in `users` |

Constraint names come from the convention in `server/db/base.py`:
`pk_transactions`, `uq_transactions_statement_id` (on `statement_id,
item_number`), `fk_transactions_statement_id_statements`,
`fk_transactions_category_code_categories`,
`ck_transactions_item_number_positive`, `ck_transactions_section_known`,
`ck_transactions_printed_date_not_empty`,
`ck_transactions_description_not_empty`.

Two indexes, declared in the model so the drift test sees them:

- The unique constraint above covers "the lines of a statement, in order"
  (BE-10).
- `ix_transactions_statement_id_category_code` on `(statement_id,
  category_code)`, for the per-category summary and the lanes (BE-12, FE-08).
  It also serves the foreign key to `categories`.

`description` is the most sensitive column: it names merchants. It never goes
in a log (BE-21) and the model's `__repr__` shows the id only.

### 3.2 Access and RLS

`enable_backend_only_rls("transactions")`, as for every table. `app_backend`
reads and writes it through the default privileges of `0001`. Per-user
filtering is code: a transaction is reached through its statement, and every
query joins to `statements.user_id` (BE-10, BE-11), each with a test that one
user cannot read or change another's.

### 3.3 The migration `0005_transactions`

Written by hand after a draft from `make db-revision M=transactions`.
`down_revision` is `0004`.

- `op.create_table("transactions", ..., schema="portal")` with the columns,
  constraints and foreign keys of 3.1, names through `op.f(...)`.
- `op.create_index` for `ix_transactions_statement_id_category_code`.
- `enable_backend_only_rls("transactions")`.
- The downgrade drops the table. Tested locally, never run in production.
- No data.

### 3.4 The model

```python
class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("statement_id", "item_number"),
        CheckConstraint("item_number >= 1", name="item_number_positive"),
        CheckConstraint(
            "section in ('purchases', 'international', 'products')", name="section_known"
        ),
        CheckConstraint("printed_date <> ''", name="printed_date_not_empty"),
        CheckConstraint("description <> ''", name="description_not_empty"),
        Index("ix_transactions_statement_id_category_code", "statement_id", "category_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE")
    )
    item_number: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    printed_date: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category_code: Mapped[str] = mapped_column(
        ForeignKey("categories.code", ondelete="RESTRICT")
    )
    doubtful: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.id}>"
```

The exact syntax is settled when the draft is written (the unique
constraint's name must come out as `uq_transactions_statement_id`).
`server/db/__init__.py` exports `Transaction`.

### 3.5 Applying to production (Article 7)

A deploy step, run by the owner from `main` after the merge (see the
"After merge" list in section 4). The agent never holds the credential.

### 3.6 Steps

One step, about 350 lines with the tests. Branch
`feat/be-29-transactions-table`, from `origin/main`, PR to `main`.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/db/models.py` | New: `Transaction` (and the imports it needs) |
| `app/api/server/db/__init__.py` | Export `Transaction` |
| `app/api/migrations/versions/0005_transactions.py` | New |
| `app/api/tests/test_transaction_model.py` | New: model tests, no database |
| `app/api/tests/test_transactions_db.py` | New: table tests, marked `db` |
| `docs/BACKLOG.md` | BE-29: spec link, status, PR links |

## 4. Verification

**At merge** (the agent runs them on the branch):

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass; the RLS invariant and the drift test now cover this table |
| 3 | `make db-upgrade && make db-current` on the local database | `0005 (head)`. A second `make db-upgrade` changes nothing |
| 4 | `psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select column_name\|\|':'\|\|data_type\|\|':'\|\|is_nullable from information_schema.columns where table_schema='portal' and table_name='transactions' order by ordinal_position"` | Twelve lines, in the order of 3.1, with the types and nullability there |
| 5 | `psql ... -Atc "select relrowsecurity from pg_class where oid='portal.transactions'::regclass"` | `t` |
| 6 | An insert with a `category_code` that does not exist | `violates foreign key constraint "fk_transactions_category_code_categories"` |
| 7 | An insert with `section = 'other'` | `violates check constraint "ck_transactions_section_known"` |
| 8 | Two inserts with the same `statement_id` and `item_number` | `violates unique constraint "uq_transactions_statement_id"` |
| 9 | Delete a statement that has transactions | The transactions are gone with it (`CASCADE`) |
| 10 | `make db-downgrade`, then `select to_regclass('portal.transactions')`, then `make db-upgrade` | An empty line, then `0005 (head)` |

**After merge (deploy, owner, from `main`).** The item stays In progress until
these pass; a Done PR records the result.

| # | Check | Expected |
|---|---|---|
| 11 | `scripts/db-backup.sh`, then read `make db-sql FROM=0004` and say "apply" | The SQL creates `portal.transactions`, its constraints and index, turns RLS on, adds one policy. No password, no data, nothing outside `portal` |
| 12 | `make db-upgrade && make db-current` against Supabase | `0005 (head)` |
| 13 | In `psql` as the owner: `select count(*) from portal.transactions;` | `0` |

Checks 11 to 13 validated by the owner on 2026-11-10 (Supabase at `0005 (head)`, `portal.transactions` empty).

## 5. Tests

Fictitious data only (`sub-fulano`, `fulano@exemplo.com`, "Fatura Cartão
Exemplo, set/2026", merchants such as "LOJA EXEMPLO 1/3"). The `db` tests reuse
the BE-31 fixtures and run in `make test-db`.

`test_transaction_model.py`

| Test | Asserts |
|---|---|
| `test_transaction_is_in_the_portal_schema` | `Transaction.__table__.schema == "portal"` and it is on `Base.metadata` |
| `test_transaction_id_default_is_uuid4` | The column default makes a `uuid.UUID` of version 4 |
| `test_transaction_repr_shows_only_the_id` | `repr` has the id and not the description |
| `test_transaction_amount_is_numeric` | `amount` is `Numeric(14, 2)` and not nullable |

`test_transactions_db.py`, marked `db`

| Test | Asserts |
|---|---|
| `test_transactions_columns` | The twelve columns, types and nullability, as in check 4 |
| `test_defaults_are_set_on_insert` | With only the required columns, `doubtful` and `reviewed` are false, and `id`, `created_at`, `updated_at` are set. Tested directly because the drift test cannot see defaults (BE-35) |
| `test_updated_at_moves_on_orm_update` | An ORM update changes `updated_at` |
| `test_unknown_category_is_refused` | An unknown `category_code` raises `IntegrityError` on the foreign key |
| `test_unknown_section_is_refused` | `section = 'other'` raises `IntegrityError` on `ck_transactions_section_known` |
| `test_item_number_must_be_positive` | `item_number = 0` raises `IntegrityError` |
| `test_empty_description_and_date_are_refused` | An empty `description` and an empty `printed_date` each raise `IntegrityError` |
| `test_item_number_is_unique_per_statement` | The same number twice in one statement fails; the same number in another statement works |
| `test_amount_keeps_two_decimals_and_allows_negative` | `-49.90` and `11906.35` round-trip as `Decimal` |
| `test_deleting_a_statement_deletes_its_transactions` | `CASCADE` removes the rows |
| `test_category_in_use_cannot_be_deleted` | Deleting a `categories` row that a transaction uses fails (`RESTRICT`), run as the owner |
| `test_app_role_reads_and_writes_transactions` | As `app_backend`, insert, select, update and delete work |
| `test_app_role_cannot_drop_transactions` | As `app_backend`, `DROP TABLE portal.transactions` fails |
| `test_downgrade_drops_the_table` | `downgrade 0004` removes the table, `upgrade head` brings it back |
| `test_models_match_migrations` | The BE-31 drift test reports no difference. It sees the columns, the foreign keys, the unique constraint and the index |

## 6. Open questions

Each with a recommended option. A question with no answer becomes an
assumption with the recommended option.

1. **What happens to the transactions when their statement row is deleted?**
   *Recommended: `CASCADE`.* A transaction has no meaning without its
   statement, and BE-15 ("delete a statement and its transactions") needs one
   delete to remove both. This differs from `statements.user_id`, which is
   `RESTRICT`: a person's statements are never lost by a side effect, but a
   statement's lines are part of it. The alternative, `RESTRICT`, makes BE-15
   delete the lines first, in code.
2. **Which values does `section` store?** *Recommended: English `purchases`,
   `international`, `products`, enforced by a check constraint.* The names of
   the columns are English by your decision, so the values follow. BE-05 maps
   `compras`, `internacional` and `produtos` to them. The interface labels
   (pt-BR) come from the frontend. The alternative is to store the extraction's
   Portuguese words as they are.
3. **How is the date stored?** *Recommended: `printed_date`, text, not empty,
   no format check.* The statement prints `dd/mm` with no year, and the real
   format is known only from the owner's real statements. A strict format
   check could refuse a real line. BE-05 validates what it imports. The
   alternative is a `date` column with the year taken from the statement,
   which needs a statement-level field that BE-28 does not have yet.
4. **Is `category_code` required?** *Recommended: yes, not null.* The
   extraction always returns a category, and `OUTROS` is the fallback. A
   transaction with no category would need a state the board does not have.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-28 and BE-30 merged, local database current | Agent | `cd app && make db-up && make db-upgrade && make db-current` | `0004 (head)` |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation |
| `pg_dump` and `psql` on the owner's machine | Owner | `pg_dump --version && psql --version` | `pg_dump` 17 or newer |
| The owner's connection string | Owner | `stat -f '%Lp' ~/.config/odiservices/supabase.env` | `600` |
| Supabase has `0004` applied | Owner | `set -a; . ~/.config/odiservices/supabase.env; set +a; make db-current` | `0004 (head)` |

**Packages.** None.

**Actions that need the owner's explicit OK.** Applying `0005` to Supabase
(checks 11 and 12), after the merge. The owner reads `make db-sql FROM=0004`
and says "apply". The agent never holds a production credential.

**Cost.** None. A failed migration leaves nothing behind.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | A `UniqueConstraint("statement_id", "item_number")` is named `uq_transactions_statement_id` by the convention (it uses the first column) | *Assumed*, from `base.py` | Check 8 and the drift test; if the name differs, the model passes an explicit name |
| 2 | Two foreign keys from one table get distinct names, `fk_transactions_statement_id_statements` and `fk_transactions_category_code_categories` | *Verified* by reading the convention (`column_0_name` and the referred table differ) | `test_unknown_category_is_refused` |
| 3 | The default privileges from `0001` reach the new table | *Verified* for `users`, `categories`, `statements` | `test_app_role_reads_and_writes_transactions` |
| 4 | The drift test does not see `server_default` (BE-35 is not done) | *Verified* by reading `migrations/options.py` | `test_defaults_are_set_on_insert` tests it directly |
