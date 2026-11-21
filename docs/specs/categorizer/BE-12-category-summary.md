# Spec — BE-12 Return a per-category summary for a statement

| | |
|---|---|
| **Backlog** | Feature: Statement board › Backend › BE-12 |
| **Story** | FE-07 (spending distribution: the bar and the legend). FE-08 also shows a count and a total per lane, see section 6, question 5 and the gaps in section 6 |
| **Prototype** | `docs/prototypes/portal/v3.html#board` |
| **Depends on** | BE-10 (Done, #89 and #91) |
| **Spec status** | Approved (2026-11-21). The owner delegated the decisions of section 6 and accepted its recommendations |
| **Date** | 2026-11-21 |

## 1. Goal

The distribution bar and its legend (FE-07) need each category's total for the
statement, and the share of the spending that each one takes. The browser must
not compute these from the lines: the server already owns the rules (a total is
the sum of stored amounts, refunds included, and a category with no positive
total has no segment). `GET /api/statements/{statement_id}/summary` returns one
row per category of the statement, with its total, its count of lines, its
count of pending doubts and its share, plus the two sums the bar needs. It is
read-only, for the signed-in user only, and it reads the same tables as BE-10.

## 2. Scope

**In scope**

- `GET /api/statements/{statement_id}/summary` and the functions behind it
  (`read_category_summary`, `category_totals`, `summary_view`), with its
  response model.
- The share rule (3.3), including the rounding, which is a Python step over the
  at most ten category rows, not over the lines.
- The 404 for missing, malformed and other users' ids, reusing BE-10's answer.
- Tests (section 5).

**Out of scope**

- The statement's lines and header: BE-10. The response does not repeat them.
- Display labels for the categories (`Investimento`): BE-16. The response
  returns `category_code` only, as BE-10 does (section 6, question 7).
- Changing a category or the reviewed flag: BE-11. The summary is not refreshed
  by the server after a change; the board calls it again.
- The lane layout and the legend text ("e mais 5 categorias"): FE-07 and FE-08.
- Any screen: FE-07 and later.

## 3. Design

### 3.1 The route

`GET /api/statements/{statement_id}/summary`, behind the Access check (BE-23,
application-wide) and `Depends(current_user)` (BE-24), as BE-10 is. The statement
is found by its id and the user in the token, never by a user id. The id is
declared as `str` and parsed with `uuid.UUID(...)` in the route, so a malformed
id is a `404`, not a `422`. The path is a new segment under the statement, so it
does not collide with BE-10's `GET /api/statements/{statement_id}`.

There is no body and no query parameter. The response is the same for every
caller, so there is nothing to vary.

### 3.2 The response

`200`, with `Cache-Control: no-store`:

```json
{
  "lines_total": "11906.35",
  "positive_total": "11948.65",
  "categories": [
    {"category_code": "INVESTIMENTO", "position": 4, "total": "4899.00",
     "transaction_count": 1, "pending_review_count": 0, "share": 41},
    {"category_code": "PESSOA FISICA", "position": 9, "total": "0.00",
     "transaction_count": 0, "pending_review_count": 0, "share": null},
    {"category_code": "OUTROS", "position": 10, "total": "-42.30",
     "transaction_count": 2, "pending_review_count": 1, "share": null}
  ]
}
```

The example is abbreviated: the real response has one element per category
(section 3.4), ten for the seeded set.

- `categories` has one element per row of `portal.categories`, including the
  categories the statement does not use. Its order is the one in section 6,
  question 4: total descending, ties by `position` ascending.
- `total` is a decimal string with two places, from `numeric(14,2)`: `"4899.00"`,
  `"-42.30"`, `"0.00"` for a category with no lines. Never a float.
- `position` is the category's `position` in `portal.categories`. It is the
  fixed order of the lanes (FE-08), so a caller can order by it without another
  read. The list itself is ordered by total (question 4).
- `transaction_count` is the number of lines of the category in the statement.
- `pending_review_count` is the number of those lines with `doubtful` true and
  `reviewed` false, the rule of BE-11 (3.6) and of BE-10's header.
- `share` is an integer percentage, or `null` (3.3).
- `lines_total` is the sum of the amounts of all the lines of the statement, as
  a decimal string. It can be negative. It is the sum of the category totals,
  because every line has a category (3.3).
- `positive_total` is the sum of the category totals that are greater than
  zero. It is the denominator of the shares, and the total of the bar's
  segments. The browser draws each segment at its `total` divided by
  `positive_total`, so the segments fill the bar exactly.
- A statement with no lines is `200`: every category has `total` `"0.00"`,
  `transaction_count` 0, `share` `null`, and `lines_total` and `positive_total`
  are `"0.00"`.

The response names no description, no line and no id other than the path's.

### 3.3 Totals and shares

**Totals.** One SQL statement groups the lines by category, with the category
table as the left side, so a category with no lines still gets its row. The
statement filter is in the join condition, not in `WHERE`, so it does not drop
the empty categories:

```sql
SELECT c.code, c.position,
       COALESCE(SUM(t.amount), 0)                               AS total,
       COUNT(t.id)                                              AS transaction_count,
       COUNT(t.id) FILTER (WHERE t.doubtful AND NOT t.reviewed) AS pending_review_count
FROM portal.categories c
LEFT JOIN portal.transactions t
       ON t.category_code = c.code AND t.statement_id = :statement_id
GROUP BY c.code, c.position;
```

`COUNT(t.id)` and not `COUNT(*)`: an empty category has one row with a `NULL`
line, and `COUNT(*)` would count it as one.

The ORM may express this differently, but the query has one `GROUP BY` and no
Python loop over the lines.

**Shares.** Computed by `summary_view` over the category rows, with `Decimal`
arithmetic, never floats. Let `P` be `positive_total`, the sum of the totals
greater than zero.

1. If `P` is zero, every `share` is `null`. This is the case of a statement with
   no positive category, such as one with only refunds.
2. Otherwise, for each category with a total greater than zero, `exact` is
   `total * 100 / P`, `floor` is its integer part and `remainder` is the rest.
   Categories with a total of zero or less get `null`.
3. `deficit` is `100 - sum(floor)`. It is at least 0 and less than the number of
   positive categories. The `deficit` categories with the largest `remainder`
   get one more point. A tie on `remainder` goes to the lower `position`.

This is the largest-remainder method. It makes the shares of the positive
categories add up to exactly 100 whenever `P` is positive. Plain rounding does
not: on the canonical fixture it adds up to 101 (section 5).

**Refunds.** A negative line lowers its category's total. A category whose total
ends up at zero or below has `share` `null`, and it has no segment in the bar.
A refund does not change the denominator of the other categories except through
`P`, which is the sum of the positive categories only.

### 3.4 Which categories are shown

All categories are returned, so the response has the same shape for every
statement, and the browser filters. FE-07's rule is a category with a total
greater than zero: a segment in the bar, and a count in the legend. In the
legend, `e mais N categorias` is the number of such categories minus three.
On the fixture that is 8 minus 3, which is the story's "e mais 5 categorias".
FE-07 does not say that rule in those words, so it is written here as the
contract for the browser (section 6, question 3).

### 3.5 Ownership and order of the work

1. Parse `statement_id`. Malformed: `404 statement_not_found`.
2. `owned_statement` of BE-10: `where id = :sid and user_id = :current.id`. No
   row: `404 statement_not_found`. The lines are read only after this.
3. The totals query (3.3), then `summary_view` in Python over at most ten rows.

Both database calls run in the threadpool, as BE-10 does.

### 3.6 Errors

The portal's format (`docs/BACKEND_GUIDELINES.md`, Errors).

| Status | `code` | `message` (pt-BR) |
|---|---|---|
| 401, 403 | from BE-23, BE-24 | unchanged |
| 404 | `statement_not_found` | `A fatura não foi encontrada.` (BE-10, unchanged) |
| 503 | `database_unavailable` | from BE-24, unchanged. Also for a `DBAPIError` in either of this route's two queries; the log carries the class name only |

The `404` is one answer for an unknown, a malformed and another user's id, with
the same body and headers except `X-Request-Id`, as in BE-10. There is no body,
so there is no `422` and no `413`.

### 3.7 Logging

The request log of BE-21 is the only log line. It records the route template,
`/api/statements/{statement_id}/summary`, never the raw path. The route writes
one `database_error` line on a `DBAPIError`, with the class name only. No total,
count, share or name appears in any line.

### 3.8 Steps

One step, estimated at about 550 to 600 lines with the tests. The estimate is
high for this kind of item: BE-10 was estimated at 220 lines and landed at 480,
and BE-11 went from 350 to 590. A split is likely, so it is planned now.
Branch `feat/be-12-category-summary`, from `origin/main`, PR to `main`.

If the code passes 500 lines, I stop and propose the split, which is the seam
between the share rule and the route:

- **Step 1** (`feat/be-12-step-1-share-rule`, PR to `main`): `summary_view`, the
  shares of 3.3, and the pure tests of section 5 (`test_shares_are_largest_remainder`,
  `test_equal_remainders_go_to_lower_position`, `test_no_positive_total_has_no_shares`,
  `test_ties_are_ordered_by_position`, `test_empty_totals_are_zero`). No route.
- **Step 2** (PR to `main`, after step 1): `category_totals`, `read_category_summary`,
  the route, the route tests and the db tests. The db empty-statement test stays
  in step 2: it is the one that catches a statement filter placed in `WHERE`.

Decision (2026-11-21): the item stays one step and may pass 500 lines, as BE-05
and BE-11 did. The split above is the fallback only if the code passes about 650
lines.

### 3.9 Files

| File | Change |
|---|---|
| `app/api/server/statements.py` | Add `category_totals(session, statement_id)` (the query of 3.3), `summary_view(rows)` (the shares), the response model `CategorySummaryView` and `CategoryTotalView`, and `read_category_summary(session, user, statement_id)`, which returns `None` for a missing or another user's statement |
| `app/api/server/routes/statements.py` | Add `GET /api/statements/{statement_id}/summary` |
| `app/api/tests/test_statement_summary.py` | New: section 5, no database |
| `app/api/tests/test_statement_summary_db.py` | New: section 5, marker `db` |
| `docs/BACKLOG.md` | At implementation: BE-12 to In progress, then the PR link. Not changed by this spec |

No migration (the grants and the RLS policy of BE-28 and BE-29 already cover
the reads), no setting, no dependency, no change to `server/main.py`, and no
change to `test_access_routes.py`: its every-route test fills the path
parameter with a sample id already (section 8, claim 2).

## 4. Verification

Everything runs when the item merges, with the local Postgres (`make db-up`).
There is no *After merge* list: no migration and no deploy. The route is checked
through the test client, with the Access verifier faked. No check needs BE-11:
the recategorized case is an in-memory copy imported through `import_statement`,
and the reviewed flag is set through the ORM.

`make test-api` passes no arguments to pytest, so single files are run as
`cd app/api && .venv/bin/python -m pytest <file>`.

| # | Check | Expected |
|---|---|---|
| 0 | Preflight: BE-10 is merged | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` prints one line |
| 1 | `cd app && make test-api` | All pass, `db` tests deselected |
| 2 | `cd app && make db-up && make test-db` | All pass, including `test_statement_summary_db.py` |
| 3 | `cd app/api && .venv/bin/python -m pytest tests/test_statement_summary.py -v` | All pass: `test_summary_requires_access`, `test_malformed_id_is_404`, `test_summary_response_headers`, `test_summary_logs_carry_no_values`, `test_no_engine_is_503`, `test_query_error_is_503_without_details`, `test_shares_are_largest_remainder`, `test_equal_remainders_go_to_lower_position`, `test_no_positive_total_has_no_shares`, `test_ties_are_ordered_by_position`, `test_empty_totals_are_zero` |
| 4 | `cd app/api && PORTAL_DATABASE_URL=postgresql+psycopg://odiservices@127.0.0.1:55432/odiservices .venv/bin/python -m pytest -m db tests/test_statement_summary_db.py -v` | All pass: `test_fixture_summary_matches_expected_table`, `test_bar_and_legend_rule_on_fixture`, `test_pending_follows_reviewed`, `test_recategorized_line_moves_the_total`, `test_refund_only_statement_has_no_shares`, `test_equal_totals_are_ordered_by_position`, `test_empty_statement_has_ten_zero_rows`, `test_other_users_statement_is_identical_to_missing` |
| 5 | The fixture's category totals, computed outside the app: `cd app && python3 -c "import json,decimal as d,collections as c;f=json.load(open('fixtures/statement-example-2026-09.json'));t=c.defaultdict(d.Decimal);[t.__setitem__(l['categoria'],t[l['categoria']]+d.Decimal(str(l['valor']))) for l in f['lancamentos']];[print(k,format(v,'.2f')) for k,v in sorted(t.items())]"` | Nine lines: `CUSTO DO CARRO 305.00`, `DESPESA ADMINISTRATIVA 682.40`, `DESPESAS FINANCEIRAS 32.25`, `FOLHA DE PAGAMENTO 3000.00`, `FORNECEDOR 1772.00`, `INVESTIMENTO 4899.00`, `MARKETING/COMERCIAL 710.00`, `OPERACIONAL 548.00`, `OUTROS -42.30`. This is the same as the table in section 5 |
| 6 | Categories seeded: `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select code, position from portal.categories order by position;"` | Ten lines, from `FORNECEDOR|1` to `OUTROS|10` |

Check 4 and the tests of section 5 cover FE-07's three scenarios on the fixture:
"the bar has one segment per category with a positive total" (the
`test_bar_and_legend_rule_on_fixture` test: eight positive categories, none of
them `PESSOA FISICA` or `OUTROS`), "the legend lists the three largest, with
41%, 25% and 15%" (the same test), and "the distribution follows category
changes" (`test_recategorized_line_moves_the_total`, which puts the line in
`FORNECEDOR` by a copy, not by BE-11's PATCH).

## 5. Tests

Fictitious data only: the canonical fixture, imported through `import_statement`
(BE-05), and copies changed in memory for the cases that need them. Access and
the user row use `tests/access_helpers.py` and the BE-24 pattern, with the
verifier faked. No call leaves the machine.

### 5.1 The expected values for the canonical fixture

The totals are computed from `app/fixtures/statement-example-2026-09.json` (check
5). `P` is `positive_total` and `L` is `lines_total`.

| `category_code` | `total` | lines | pending | `share` |
|---|---|---|---|---|
| `INVESTIMENTO` | 4899.00 | 1 | 0 | 41 |
| `FOLHA DE PAGAMENTO` | 3000.00 | 1 | 0 | 25 |
| `FORNECEDOR` | 1772.00 | 3 | 0 | 15 |
| `MARKETING/COMERCIAL` | 710.00 | 2 | 0 | 6 |
| `DESPESA ADMINISTRATIVA` | 682.40 | 2 | 0 | 6 |
| `OPERACIONAL` | 548.00 | 2 | 1 | 5 |
| `CUSTO DO CARRO` | 305.00 | 2 | 0 | 2 |
| `DESPESAS FINANCEIRAS` | 32.25 | 2 | 0 | 0 |
| `PESSOA FISICA` | 0.00 | 0 | 0 | null |
| `OUTROS` | -42.30 | 2 | 1 | null |

- `P` is 11948.65, and `L` is 11906.35, the statement total.
- The shares in exact terms are 41.0004, 25.1074, 14.8301, 5.9421, 5.7111,
  4.5863, 2.5526 and 0.2699 for the eight positive categories, in the same row
  order. Their floors sum to 96, so four points go to the largest remainders:
  `MARKETING/COMERCIAL` (.942), `FORNECEDOR` (.830), `DESPESA ADMINISTRATIVA`
  (.711) and `OPERACIONAL` (.586). Plain rounding gives 41, 25, 15, 6, 6, 5, 3,
  0, which is 101. The rule gives the table's 100.
- Rounded against `L` instead of `P`, the shares would add up to about 100.36%.
  That is why `P` is the denominator (section 6, question 2).
- The legend: the top three are `INVESTIMENTO` 41, `FOLHA DE PAGAMENTO` 25 and
  `FORNECEDOR` 15, and the positive categories are eight, so `e mais 5`.
- The order of the rows is the order of the table.

`test_statement_summary.py` (no database). The session is the fake of
`test_statement_read.py`, extended with an `execute` that answers the totals
query from a list of rows of the shape `(code, position, total, count, pending)`.
The pure tests call `summary_view` directly.

| Test | App | Asserts |
|---|---|---|
| `test_summary_requires_access` | Plain `create_app` with the Access verifier faked, no overrides | No token gives `401`, and the route's queries are never reached |
| `test_malformed_id_is_404` | Overrides: `get_session` a fake session, `current_user` a `User` | `abc-123`, a uuid one character short and `%20` each give `404` with `statement_not_found` |
| `test_summary_response_headers` | Overrides, as above | A `200` carries `Cache-Control: no-store`; totals are strings (`"4899.00"`, `"-42.30"`), shares are integers or `null` |
| `test_summary_logs_carry_no_values` | Overrides, as above | The request line holds `"route": "/api/statements/{statement_id}/summary"` and no id. A planted total `1234.56` and a category text `CATEGORIA SIGILO` appear in no line |
| `test_no_engine_is_503` | Plain `create_app` with no `PORTAL_DATABASE_URL`, real `get_session`, valid token | `503` with `database_unavailable` |
| `test_query_error_is_503_without_details` | Overrides, a session that raises `OperationalError` with a host name | `503` with `database_unavailable`; the host is in neither the body nor the log |
| `test_shares_are_largest_remainder` | Pure: `summary_view` on the 10 rows of 5.1 | Shares `41, 25, 15, 6, 6, 5, 2, 0, null, null`; the positive shares sum to 100 |
| `test_no_positive_total_has_no_shares` | Pure: rows whose totals are zero or negative | `positive_total` `"0.00"`, every `share` `null` |
| `test_ties_are_ordered_by_position` | Pure: two rows with equal totals, `10.00` each | The lower `position` comes first, and the two shares are `50` and `50` |
| `test_empty_totals_are_zero` | Pure: ten rows with no lines | Ten elements, every `total` `"0.00"`, `lines_total` `"0.00"`, every `share` `null` |

Also in this file, `test_equal_remainders_go_to_lower_position` (pure): three
rows with totals `1.00`, `1.00`, `1.00` give shares `34`, `33`, `33`, the spare
point going to the lowest `position`. It asserts that the three add up to 100.

`test_statement_summary_db.py` (marker `db`, local Postgres, as `app_backend`)

| Test | Asserts |
|---|---|
| `test_fixture_summary_matches_expected_table` | The import of the fixture, then the response: the ten rows of 5.1 in that order, with their `total`, `transaction_count`, `pending_review_count` and `share`; `lines_total` `"11906.35"`; `positive_total` `"11948.65"` |
| `test_bar_and_legend_rule_on_fixture` | The categories with `total` greater than zero are eight, and none is `PESSOA FISICA` or `OUTROS`. The first three are `INVESTIMENTO` 41, `FOLHA DE PAGAMENTO` 25, `FORNECEDOR` 15; eight minus three is five |
| `test_pending_follows_reviewed` | Set `reviewed` true on "Software Gestão Teste" through the ORM (not the PATCH of BE-11): `OPERACIONAL` shows `pending_review_count` 0 and `transaction_count` 2 |
| `test_recategorized_line_moves_the_total` | An in-memory copy of the fixture with line 8 ("Notebook Loja Fictícia", 4899.00) set to `FORNECEDOR`, imported as a new statement. `FORNECEDOR` is first with `total` `"6671.00"`, `transaction_count` 4 and `share` 56; `INVESTIMENTO` is `"0.00"` with `share` `null`; the positive categories are seven, so `e mais 4`; `positive_total` stays `"11948.65"`; `lines_total` stays `"11906.35"` |
| `test_refund_only_statement_has_no_shares` | A payload with one line, "Estorno Exemplo", `-5.50`, in `OUTROS`, total `-5.50`: `positive_total` `"0.00"`, every `share` `null`, `OUTROS` last with `"-5.50"` |
| `test_equal_totals_are_ordered_by_position` | A payload of "Loja Exemplo" `10.00` in `FORNECEDOR` and "Loja Exemplo" `10.00` in `OPERACIONAL`, total `20.00`: `FORNECEDOR` before `OPERACIONAL`, shares `50` and `50` |
| `test_empty_statement_has_ten_zero_rows` | A statement with no lines, inserted through the ORM (BE-05 refuses an empty import, as BE-10's null-total test does): ten rows, `"0.00"` everywhere, counts 0, shares `null` |
| `test_other_users_statement_is_identical_to_missing` | A second user gets `404` for the first user's statement, with the same status, body bytes and headers as for a random uuid4, except `X-Request-Id`. The first user gets `200` |

## 6. Open questions

Each question had a recommendation. On 2026-11-21 the owner delegated the
decisions and the recommendations were adopted for all seven questions, and for
the size exception of 3.8.

1. **A separate route or the summary inside BE-10's `GET`.** *Recommended: a
   separate route, `GET /api/statements/{statement_id}/summary`.* The board
   reads the lines once and the summary once, and the summary is a different
   aggregate with its own rules. Putting it in BE-10 would change an approved,
   merged response, and every read of the lines would compute the totals, which
   FE-06 and FE-08 do not need. The alternative is an embedded `categories` list
   in BE-10's response. It saves one request and couples two shapes.

2. **Does the server return the share, and what is the denominator?**
   *Recommended: the server returns `share` as an integer percentage, by the
   largest-remainder rule of 3.3, with `positive_total` (the sum of the positive
   category totals) as the denominator.* Then the shares add up to 100, the
   legend and the bar use the server's numbers, and no float is involved.
   A refund is treated like any other line: it lowers its category, and it
   takes no share. A zero or negative `positive_total` gives `null` for every
   share. The alternative is totals only, with the browser computing shares.
   That keeps the rounding in the browser, where the same rule would have to be
   written again. The denominator `lines_total` (the statement total) is
   rejected: with refunds, its shares add up to about 100.36%.

3. **Are categories without spending included?** *Recommended: all categories,
   each with a row, including zero and negative totals, and the browser filters
   with `total > 0`.* FE-07 says "a segment per category with a positive total"
   and "e mais 5 categorias", which is eight positive categories minus three.
   The rule is the browser's, and the same response serves FE-08, which needs
   the zero lane (`PESSOA FISICA`) and the negative one (`OUTROS`, -R$ 42,30).
   The alternative is only the categories with lines, which drops `PESSOA FISICA`
   and makes the browser fill the gaps.

4. **Order.** *Recommended: total descending, ties by `position` ascending.* It
   is the bar's and the legend's order, so the server's list is already the
   legend. Each row carries `position`, so FE-08 can put its lanes in their
   fixed order from this response, without a second read. The lanes still need
   the labels (question 7). The alternative is the fixed `position` order for
   every caller, with the browser sorting for the legend.

5. **Counts per category.** *Recommended: yes, `transaction_count` and
   `pending_review_count`, from the same `GROUP BY`.* FE-08 shows "3" and "1
   para revisar" per lane, and the rule for "para revisar" is the one that BE-10
   and BE-11 already own. The cost is two columns. The alternative is totals and
   shares only, and the lanes count the lines in the browser, repeating the rule.

6. **The statement total and the sum of the lines.** *Recommended: `lines_total`,
   the sum of all amounts, as a decimal string, and no repeat of the header
   `total`.* The header total is BE-10's field, and FE-06 reads it there. The
   sum is the value the shares are about, and it is always present, even when a
   header total is `null` (BE-28 allows it). It is also the check of the
   fixture: `lines_total` equals `11906.35` only if no line is missing from the
   categories. The alternative is to return both `total` and `lines_total`, so
   the board shows the two numbers side by side and the difference is visible.

7. **Display labels in this response.** *Recommended: not in this item. The
   response returns `category_code` only, and BE-16 decides where the labels
   come from.* `portal.categories.label` already holds the pt-BR labels (for
   example `Investimento`, `Folha de pagamento`), so the `GROUP BY` could return
   them at no cost. The question belongs to BE-16, which the backlog marks as
   the item that decides between the API and the frontend. The alternative is
   to add `label` here now, with BE-16 confirming it.

### Gaps for the owner

These are gaps between the stories and the data or the backlog. This spec does
not fix them. It records them for the owner to decide.

- **Labels (FE-07, FE-08).** FE-07's legend shows "Investimento" and FE-08's
  lanes show "Fornecedor". The labels are in `portal.categories.label`, but
  FE-07 depends only on BE-12, not on BE-16, which decides where the labels come
  from (question 7).
- **Moving a card (FE-07, third scenario).** "The distribution follows category
  changes" needs BE-11's PATCH. FE-07 lists only BE-12 as its dependency, so the
  backlog should list BE-11 too. The check in section 4 uses an in-memory copy
  instead, so BE-12 can be done first.
- **What the shares divide (FE-07, first scenario).** The story says the
  distribution shows "how the statement total splits", but the shares here
  divide by `positive_total`, 11948.65, not by the statement total, 11906.35.
  On the fixture both give 41, 25 and 15 for the legend. With refunds they
  differ, and the owner should confirm the wording of the story (question 2).
- **Lane totals and counts (FE-08).** FE-08 shows a count and a total per lane,
  and the pending count per lane. It does not depend on BE-12 in the backlog. If
  it uses this response, its dependency list should include BE-12.

## 7. Prerequisites

| Prerequisite | Provided by | Preflight command | Expected |
|---|---|---|---|
| BE-10 merged: `GET /api/statements/{statement_id}` exists | Agent | `cd app/api && grep -n 'get("/api/statements/{statement_id}"' server/routes/statements.py` | One line |
| The canonical fixture exists | Agent | `cd app && test -f fixtures/statement-example-2026-09.json && echo ok` | `ok` |
| The categories are seeded (10, positions 1 to 10) | Agent | `cd app && psql postgresql://odiservices@127.0.0.1:55432/odiservices -Atc "select count(*) from portal.categories;"` | `10` |
| Local Postgres at the head revision | Agent | `cd app && make db-up && make db-current` | `0005 (head)` |
| The Access verifier can be faked in tests | Agent | `cd app && make test-api` | All pass |
| Local Docker (for `make test-db`) | Owner | `docker info >/dev/null && echo ok` | `ok` |
| Owner's answers to section 6 | Owner | (none) | Recorded: the recommendations were adopted (2026-11-21) |

**Packages.** None.

**Actions that need the owner's explicit OK.** None beyond the PR. No production
database, no deploy.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | The route takes the user as `Depends(current_user)`, as BE-10 does | *Verified*, `server/routes/statements.py` (BE-10's `get_statement`) | Check 3 |
| 2 | The every-route-is-protected test fills a path parameter with a sample id, so the new route is covered with no edit | *Verified*, `app/api/tests/test_access_routes.py`, `test_every_route_is_protected_except_the_list`, lines 93 to 100 | Check 1 |
| 3 | Every transaction has a category, so the sum over the categories is the sum of the lines (`lines_total`) | *Verified*, `server/db/models.py`: `Transaction.category_code` is a non-null foreign key to `categories.code` | Check 4: `lines_total` `"11906.35"` |
| 4 | `portal.categories` holds the ten codes of the canonical fixture at positions 1 to 10 | *Verified*, `app/api/migrations/versions/0003_categories.py` (`SEED`) | Check 6 |
| 5 | The migration head is `0005` | *Verified*, the file listing of `app/api/migrations/versions/` (`0005_transactions.py` is the last) | Preflight, row 4 |
| 6 | An ORM outer join whose statement filter sits in the `ON` clause, with `COUNT(t.id) FILTER (WHERE ...)`, gives one row per category with the counts above | *Assumed* | `test_fixture_summary_matches_expected_table`, `test_empty_statement_has_ten_zero_rows` |
| 7 | `COALESCE(SUM(numeric(14,2)), 0)` is returned as a `Decimal`, and `money_text` (`:.2f`) gives two places even when the sum has no scale | *Assumed* | `test_empty_statement_has_ten_zero_rows` (`"0.00"`) and check 5's totals |
| 8 | The fake session of `test_statement_read.py` can answer a `GROUP BY` through `execute` as well, if it is extended with the rows | *Assumed* | First run of `test_statement_summary.py` |
| 9 | The shares are integers and the largest-remainder rule gives the table of 5.1 | *Assumed* from a hand computation on the fixture (5.1 lists the exact values); the code is checked by the test | `test_shares_are_largest_remainder` |
| 10 | Starlette matches `{statement_id}` to one path segment, so `/api/statements/{id}/summary` is not taken by BE-10's route | *Assumed* | `test_summary_response_headers` (a `200`, not a `404`) |

## 9. Notes for the implementer

- The shares are computed in Python over at most ten rows. This is not a loop
  over the lines, and the SQL does all the aggregation.
- `summary_view` takes the rows as plain values, so the share rule is tested
  with no database.
- `read_category_summary` returns `None` for a missing or another user's
  statement, as `read_statement` does, and the route maps it to the 404.
