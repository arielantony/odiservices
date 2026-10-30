# OdiServices — instructions for Claude Code

OdiServices Portal is Odisseia's internal portal. Its first service is the
categorizer: it reads a credit card statement (PDF), extracts the
transactions and lets the finance team review their categories on a board.

The documents in `docs/` are the source of truth. Read the ones that apply
before changing anything:

| Document | What it governs |
|---|---|
| `docs/CONSTITUTION.md` | Language, HTML prototype before any frontend change |
| `docs/BACKLOG.md` | Items, status, dependencies and the order of work |
| `docs/specs/README.md` | What a spec is and how it is approved |
| `docs/specs/<area>/<ID>-*.md` | How each item is built |
| `docs/FRONTEND_GUIDELINES.md` | Brief → prototype → stories → spec → implementation |
| `docs/TESTING_GUIDELINES.md` | Unit tests, fictitious data, the canonical fixture |
| `docs/proposals/monorepo-and-react.md` | The monorepo layout and the React stack (approved) |
| `docs/stories/` | Gherkin stories for frontend items |
| `docs/prototypes/portal/v3.html` | The approved design (with the amendments in its README) |

## How work is done

- **One backlog item at a time,** and only items whose status is **Ready**
  (spec approved). The order is in `docs/BACKLOG.md`. The first slice is
  BE-17 → BE-18, BE-19 → BE-20, BE-21 → BE-01, with FE-23 in parallel, then
  FE-01.
- **The approved spec is the contract.** Implement what it says, with the
  file names, routes, settings and tests it lists. Don't add scope that
  belongs to another item.
- **If the spec is wrong or incomplete, stop.** Propose the change to the
  spec and wait for the owner to approve it before continuing. The same
  applies to the prototype for anything visual.
- **Tests come with the code.** Write the tests listed in the spec's Tests
  section. An item is Done only when they pass and the spec's verification
  table has been checked.
- **When an item is done,** report what was built, the test output and the
  verification results, and update its status in `docs/BACKLOG.md`. Don't
  start the next item until the owner says so.
- **Don't commit or push unless asked.**

## Stack and commands

- `app/` is a monorepo: `api/` (FastAPI, Python 3.14), `web/` (React, Vite,
  TypeScript), `fixtures/` (shared fictitious test data), one `Makefile`.
- **Python:** a uv-managed venv in `app/api/.venv`. Dependencies are pinned
  with `==` in `requirements*.txt`, compiled from `requirements*.in`
  (BE-19).
- **Node:** version 24 through nvm (`app/web/.nvmrc`). This machine defaults
  to Node 25, so run `nvm use` first.
- **Yarn 4** through corepack (`corepack enable`). Never npm or pnpm.
  `yarn install --immutable`, exact versions, `nodeLinker: node-modules`.
- **Installing packages** is authorized only for the packages a Ready item's
  spec lists. Ask before installing anything else, including global tools.
- The Makefile targets (`make dev`, `make serve`, `make test`,
  `make test-api`, `make test-web`, `make build-web`, `make setup-web`) are
  created by BE-17 and FE-23. Use them once they exist.

## Language

- English for code, identifiers, comments, docs, file names and commit
  messages.
- Brazilian Portuguese for every text the user reads in the interface.

## Security and data (never break these)

- **No real financial data, ever.** Real statements, transactions, customers
  or suppliers never go into code, tests, fixtures, snapshots, logs, docs,
  screenshots, issues or commit messages. Tests use the canonical fictitious
  fixture ("Fatura Cartão Exemplo, set/2026",
  `app/fixtures/statement-example-2026-09.json`) or other obviously fictitious
  data.
- **The owner's real statement** is used only for the manual checks marked
  *Pending validation*, uploaded through the running portal with the owner
  present. The result is recorded as "validated on <date>", with no data.
- **Uploaded PDFs are sensitive.** `input/` and `outputs/` are never
  committed, served or copied into the Docker image.
- **No secrets in the repo.** `.env` files are never committed, never read by
  tests, and never served. `.env.example` lists variable names only.
- **The Supabase service-role key stays on the server.** It never reaches the
  browser or the frontend bundle.
- **No PII in logs.** No query strings, bodies, headers, IPs, emails, file
  names or transaction descriptions (BE-21).
- **No real external calls in tests.** Supabase, Cloudflare Access and
  Anthropic are replaced by fakes.

## Things that are easy to get wrong

- The vanilla categorizer moves to `app/web/legacy/` (FE-23). It is a
  behavior reference only: it is not served and is deleted after FE-13.
- `kanban/` is removed by BE-17, after the backup tarball in
  `~/odiservices-backups/` described in its spec.
- The standard screen width is 1360 px. FE-01 is checked at 1280 px and
  1360 px.
- `ask_pdf.py` at the repo root moves into `app/api/` only when BE-03 needs
  it.
- CSP is BE-32, a separate item. BE-01 doesn't include it.
