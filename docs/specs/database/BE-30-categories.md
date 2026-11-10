# Spec — BE-30 Model categories as a constrained set

| | |
|---|---|
| **Backlog** | Platform › Database › BE-30 |
| **Depends on** | BE-31 (Done) |
| **Spec status** | Approved (2026-11-10), with the recommended answers in section 6. Not Ready until this PR is merged |
| **Date** | 2026-11-10 |

## 1. Goal

A transaction's category has to be one of a fixed set, and the set has to be
stored in the database, not only in code. The owner wants to add categories
later, so the set is a **lookup table** (`portal.categories`): the transactions
table (BE-29) refers to a category by a foreign key, and the database refuses
any other value. This item creates the table, seeds it with the ten categories
the business uses today, and adds the model. It creates no transaction and no
code that classifies one.

## 2. Scope

**In scope**

- The table `portal.categories` and its migration `0003_categories`.
- The seed of the ten current categories, in the same migration.
- The ORM model `Category` in `server/db/models.py`.
- Tests against the local Postgres (section 9).

**Out of scope**

- The `transactions` table and its foreign key: BE-29. This item only makes
  the target of that key.
- Classifying a transaction, and the rules that decide a category (the
  statement classifier): a later item of the categorizer.
- Screens that show or pick a category: FE items.
- Roles or per-user categories: BE-34.
- Adding a category in the future: a new row by the owner, through a
  migration or a SQL statement run by the owner (Article 7). No endpoint.

## 3. Design

### 3.1 The categories

The ten values are the ones in the business's classification prompt
(`prompt-pdf.md`, sections 2 and 3, and the same list in the POC at
`docs/prototypes/portal/v1-generate.py`):

| `code` | Label (pt-BR, shown in the interface) | `auto_assign` |
|---|---|---|
| `FORNECEDOR` | Fornecedor | true |
| `OPERACIONAL` | Operacional | true |
| `MARKETING/COMERCIAL` | Marketing/Comercial | true |
| `INVESTIMENTO` | Investimento | true |
| `DESPESA ADMINISTRATIVA` | Despesa administrativa | true |
| `FOLHA DE PAGAMENTO` | Folha de pagamento | **false** |
| `CUSTO DO CARRO` | Custo do carro | **false** |
| `DESPESAS FINANCEIRAS` | Despesas financeiras | true |
| `PESSOA FISICA` | Pessoa física | true |
| `OUTROS` | Outros | true |

`FOLHA DE PAGAMENTO` and `CUSTO DO CARRO` are used only when the owner says
so (the prompt: "use apenas se eu indicar"). `auto_assign = false` records
that in the data: the classifier never picks such a category on its own. The
category stays in the set so the owner can choose it by hand.

### 3.2 The columns

| Column | Type | Rules |
|---|---|---|
| `code` | `text` | Primary key. Not empty, uppercase (check `code = upper(code)`). The stored value the transactions refer to. Stable: changing a code is a migration, never an update |
| `label` | `text` | Not null, not empty. Shown to the user, in Brazilian Portuguese |
| `auto_assign` | `boolean` | Not null, default `true`. See 3.1 |
| `position` | `integer` | Not null, unique. The order the interface lists them |
| `created_at` | `timestamptz` | Not null, default `now()` |

Constraint names come from the naming convention in `server/db/base.py`:
`pk_categories`, `uq_categories_position`, `ck_categories_code_not_empty`,
`ck_categories_code_uppercase`, `ck_categories_label_not_empty`.

Why a text key and not a `uuid`: the code is what the business and the
prompt already use, it is readable in a `psql` query, and it is what a
transaction row will show. The key is never reused.

### 3.3 The migration `0003_categories`

Written by hand after a draft from `make db-revision M=categories` (BE-31,
3.4). `down_revision` is `0002`.

- `op.create_table("categories", ..., schema="portal")` with the columns and
  constraints of 3.2.
- `enable_backend_only_rls("categories")` from `migrations/helpers.py`, so
  RLS is on with one policy for `app_backend`.
- The seed: `op.bulk_insert` of the ten rows of 3.1, in that order, with
  `position` 1 to 10. The seed is part of the schema, so it lives in the
  migration and not in a script.
- The downgrade drops the table. It is tested locally and never run in
  production (BE-31, 3.4).

### 3.4 The model

```python
class Category(Base):
    __tablename__ = "categories"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    auto_assign: Mapped[bool] = mapped_column(default=True, server_default=true())
    position: Mapped[int] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # + the CheckConstraints and the unique constraint, named as in 3.2
    def __repr__(self) -> str:
        return f"<Category {self.code}>"
```

`server/db/__init__.py` exports `Category`, so `migrations/env.py` sees it on
`Base.metadata`. The drift test `test_models_match_migrations` (BE-31) checks
the model against the migration.

### 3.5 Applying to production (Article 7)

Same loop as BE-27, section 3.5, with the same rule: every command against
Supabase is the owner's.

0. **Backup:** `scripts/db-backup.sh` (BE-27 era) before the change.
1. **Plan:** `make db-sql FROM=0002` prints the SQL and connects to nothing.
   The owner reads it and says "apply". The approval covers that SQL only.
2. **Apply:** `make db-upgrade`, then `make db-current` shows `0003 (head)`.
3. **No redeploy.** Nothing in the running server reads the table yet.

### 3.6 Steps

One step. About 200 lines with the tests, under the limit. Branch
`feat/be-30-categories`, from `origin/main`, PR to `main`.

### 3.7 Files

| File | Change |
|---|---|
| `app/api/server/db/models.py` | New: `Category` |
| `app/api/server/db/__init__.py` | Export `Category` |
| `app/api/migrations/versions/0003_categories.py` | New: table, RLS, seed |
| `app/api/tests/test_categories.py` | New: unit tests of the model (9.1) |
| `app/api/tests/test_categories_db.py` | New: `db` tests against the migrated database (9.2) |
| `docs/BACKLOG.md` | BE-30 set to In progress, then Done, with the PR linked |

## 4. Verification

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass, the BE-27 and BE-31 ones included |
| 3 | `make db-upgrade` on the local database, then `make db-current` | `0003 (head)` |
| 4 | Local `psql` as the owner: `select code, label, auto_assign, position from portal.categories order by position;` | Ten rows, the values of 3.1, in that order |
| 5 | Local `psql`: `select count(*) from portal.categories where auto_assign = false;` | `2` |
| 6 | `make db-downgrade` then `make db-upgrade` on the local database | Both succeed; the seed is back after the upgrade |
| 7 | *Owner, when applying to Supabase:* `make db-sql FROM=0002`, read it, say "apply", then `make db-upgrade` and `make db-current` | `0003 (head)`. The owner runs it; the agent never holds the credential |
| 8 | *Owner, after step 7:* `select count(*) from portal.categories;` | `10` |

Checks 7 and 8 are *Pending validation* only in the sense that they need the
owner's production database. They are not optional: the item is Done when
they pass.

## 5. Steps of the work (Article 6)

Single PR. No feature branch: `feat/be-30-categories` from `origin/main`.

## 6. Open questions

Answered by the owner on 2026-11-10: all four, with the recommended option.

1. **Does the owner want `auto_assign`?** *Answer: yes (recommended).* It records the
   "use only if I say so" rule in the data, so the classifier cannot pick
   `FOLHA DE PAGAMENTO` or `CUSTO DO CARRO` by mistake. Without it the rule
   lives only in the prompt.
2. **Can `app_backend` change the categories?** *Answer: no, read only (recommended).*
   The default privileges from `0001` give read and write on new tables. This
   item would revoke `INSERT`, `UPDATE` and `DELETE` on `portal.categories`
   from `app_backend`, so the set changes only through a migration or a SQL
   run by the owner. The portal does not need to add categories in this item.
3. **Is the list of ten complete?** *Answer: yes, these ten (recommended).* They are
   the business's list today. A new category later is a new row, by migration.
4. **Label language.** *Answer: pt-BR in the `label` column (recommended).* It is the
   text the user reads (`CLAUDE.md`, Language). The `code` stays in English
   and uppercase, as the classifier returns it.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-31 migration tooling and the local database | Agent | `cd app && make db-current` | `0002 (head)` once BE-27 is applied locally |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded in this spec before implementation |
| Production apply (check 7) | Owner | `ssh -i ~/.ssh/odiservices_lightsail -o IdentitiesOnly=yes deploy@3.143.109.68 'sudo grep -c ^PORTAL_DATABASE_URL= /etc/odiservices/.env'` | `1` (no value printed) |

## 8. Assumptions to verify

1. **`op.bulk_insert` writes the seed in one transaction with the table.**
   *Assumed.* Smoke test in step 1: run the migration on the empty local
   database and count the rows.
2. **The `CHECK (code = upper(code))` on `MARKETING/COMERCIAL` holds.**
   *Verified:* `upper('MARKETING/COMERCIAL') = 'MARKETING/COMERCIAL'`.

## 9. Tests

### 9.1 Unit (`test_categories.py`)

- `test_repr_shows_the_code`: `repr` of a `Category` shows the code, not the label.
- `test_seed_list_matches_the_prompt`: the seed constant in the migration
  equals the ten codes of 3.1, in order. Fixture: the list in the test itself.
- `test_only_two_categories_are_manual`: exactly `FOLHA DE PAGAMENTO` and
  `CUSTO DO CARRO` have `auto_assign = False` in the seed.

### 9.2 `db` (`test_categories_db.py`)

- `test_seed_has_ten_rows_in_order`: the table has the ten rows, `position` 1 to 10.
- `test_lowercase_code_is_refused`: inserting `fornecedor` raises `IntegrityError`.
- `test_empty_label_is_refused`: inserting an empty label raises `IntegrityError`.
- `test_duplicate_position_is_refused`: a second row with `position` 1 raises `IntegrityError`.
- `test_app_role_reads_categories`: as `app_backend`, `SELECT` returns the ten rows.
- `test_app_role_cannot_write_categories`: as `app_backend`, `INSERT` fails
  (only if owner answers question 2 with the recommended option).

Fixtures: the migrated test database from BE-31 (`test_migrations_db`). No
real data; the categories are the business's own list, which is not personal data.
