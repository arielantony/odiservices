# Testing Guidelines — OdiServices

How we test the portal. This guide applies to any person or AI agent writing
code in `app/`.

## Rules

1. **Every backlog item ships with unit tests.** The tests are listed in the
   item's spec (the **Tests** section in `docs/specs/README.md`) before
   implementation starts. They are written first, or alongside the code, never
   afterwards.
2. **Fictitious data only.** Tests, fixtures, snapshots and logs never contain
   real lançamentos, real customers or real suppliers, and are never copied
   from a real statement, even partially. The canonical fixture is below.
3. **An item is Done only when its unit tests pass,** in addition to the
   checks in its spec and, for stories, the Gherkin scenarios.
4. **Tests don't touch the outside world.** No real Supabase, Cloudflare
   Access or Anthropic calls. Those boundaries are replaced in tests by fakes
   that return fictitious data.
5. **No secrets in tests.** Settings are built in code. Tests never read
   `.env`.

## Kinds of tests

| Kind | What | Where | Runner | Backlog |
|---|---|---|---|---|
| Unit (backend) | Functions, routes and middleware, through the app factory with test settings | `app/api/tests/` | pytest + httpx (FastAPI `TestClient`) | Every BE item |
| Unit (frontend) | Components and hooks, rendered in jsdom | `app/web/src/**/*.test.tsx` | Vitest + Testing Library (`docs/proposals/monorepo-and-react.md`, approved) | Every FE item |
| Scenarios | The Gherkin stories in `docs/stories/`, in a real browser | `app/e2e/` | pytest-bdd + Playwright | QA-03 |
| Manual check | The browser checks in each spec's verification table | — | Chrome DevTools | Every FE item |

The paths follow the approved monorepo layout.

## The canonical fixture

All tests that need a statement use the same fictitious one. It is the
statement shown in prototype v3, so the prototype, the stories and the tests
describe the same data:

- **Statement:** "Fatura Cartão Exemplo, set/2026".
- **Size and total:** 17 transactions, total R$ 11.906,35.
- **Doubts:** 2 transactions are marked as doubts: "Software Gestão Teste" in
  Operacional and "Compra Não Identificada" in Outros.
- **Moved card:** "Papelaria Fictícia" was moved by the user.
- **Source:** `docs/prototypes/portal/v3-generate.py` (`cards`) is the source.

It lives in `app/fixtures/statement-example-2026-09.json`, and both `api/` and
`web/` tests read it. Changing it means updating the prototype generator and
the stories in the same change.

Additional fixtures are allowed when a test needs a case the canonical one
doesn't have, such as an empty statement or one that failed. They follow the
same rules: obviously fictitious names (Exemplo, Fictícia, Teste, Demo) and
round dates in the fixture's period.

## Real data in manual validation

Some checks can only be done with a real statement. An example is FE-01's
board rows, marked *Pending validation* in the backlog. In those cases:

- the real statement is uploaded only through the running portal, by the
  owner or with the owner present;
- it is never committed, never turned into a fixture, and never pasted into
  issues, specs or chats;
- screenshots of it are not saved to `docs/`, the scratchpad or anywhere else;
- the result is recorded in the backlog as "validated on <date>", with no data.

## Running the tests

These commands are defined when the first item is implemented (BE-17 for
`api/`, FE-23 for `web/`):

- `make test` runs everything;
- `make test-api` runs the backend tests;
- `make test-web` runs the frontend tests.
