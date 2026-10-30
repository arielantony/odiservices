# OdiServices Portal — Backlog

## How this backlog works

**Features and platform.** A **feature** is a capability the user can see,
such as uploading a statement or reviewing it on the board. The **platform**
holds the foundations that serve every feature: project setup, auth, database,
deployment and quality.

**One subsection per area.** Each feature has a **Frontend** and a **Backend**
subsection. Platform sections use **Backend**, **Infrastructure** or
**Quality**.

**Each area has a stage**, shown under its heading:

| Stage | Format | When |
|---|---|---|
| Outline | Bullet list of shallow items, each with a short context line | Before prototyping or technical design starts in that area |
| Planned | Table of stories and tasks that cover the whole feature in that area | From the moment prototyping (frontend) or technical design (backend) starts |

**Moving from Outline to Planned.** The bullet list is replaced by a table.
Every outline item must end up in one of three places:

- kept as a row, with the same ID;
- split into several rows, with new IDs and "Replaces BE-NN" in the notes;
- listed under **Dropped** with a reason.

Nothing disappears silently.

**IDs never change and are never reused.**

| Prefix | Meaning |
|---|---|
| `FE-` | Frontend story or task |
| `BE-` | Backend task |
| `OPS-` | Infrastructure task |
| `QA-` | Quality task |

Items still in the outline stage get an ID too, so that other items can depend
on them.

**Status lives here and only here.** The `@draft` and `@ready` tags in the
`.feature` files and the table in `docs/stories/README.md` mirror this file and
are updated in the same change.

| Status | Meaning |
|---|---|
| Needs prototype | Frontend only. No approved design yet, so no Gherkin |
| Draft | Written, but its prototype or its spec is not approved |
| Ready | Prototype (frontend) and spec approved, dependencies known. Can be started |
| In progress | Being implemented |
| Pending validation | Implemented, unit tests and every other check pass; some checks wait for real data the owner provides (the note under the item says which). Never used for checks that wait on a later item: those belong in that item's spec |
| Done | Implemented and verified: unit tests pass and, for stories, every scenario passes |

**Types:** *Story* means user-facing behavior with a Gherkin `.feature` file.
*Task* means technical or decision work with no user-facing behavior of its
own.

**Specs.** Every story and task gets a spec in `docs/specs/` before
implementation (see `docs/specs/README.md`). The **Item** column links to the
story, and the **Spec** column to its spec.

**Pull requests.** The **PRs** column lists every pull request for the item,
in the order they were opened: step PRs, follow-ups and the final feature →
`main` PR. Each one is a reference link, `[#N]`, defined in the **PR links**
block at the end of this file. Right after `gh pr create`, the same branch
gets a commit that adds `[#N]` to the row and its definition to that block
(`docs/CONSTITUTION.md`, Article 6). Rows with no PRs leave the cell empty.

**Tests.** Every item ships with unit tests on fictitious data, listed in its
spec (see `docs/TESTING_GUIDELINES.md`).

The frontend process is described in `docs/FRONTEND_GUIDELINES.md`. Open
proposals live in `docs/proposals/`.

---

## Bootstrap

- [x] Strip `app/` down to the website pages and their dependencies
  - Context: the Cloudflare Workers backend, build scripts, tests, migrations and tooling are all dropped so work starts fresh. Only the static frontend and the vendored `chart.umd.min.js` remain, so there is no `package.json`. A backup of the old tree is at `~/odiservices-backups/app-pre-bootstrap-2026-10-29.tar.gz`. The rules, contracts, migration and `access-jwt.ts` code is recoverable from there as reference for the items below.
- [x] Create `app/portal/` as the folder that hosts the portal (the main app)
  - Context: `app/portal/index.html` is a landing page listing the available services.
- [x] Create `app/portal/categorizer/` as the categorizer feature (a service within the portal)
  - Context: holds the moved board and upload shell (`index.html`, `style.css`, `shell.css`, `js/`, `vendor/`). The tags for the missing `delete-notice` css and js were removed; `shell.js` already guards `window.DeleteNotice`.
- [x] Leave only the files needed to build and see the site
  - Context: view it with `python3 -m http.server` run in `app/portal`, then open `/` and `/categorizer/`. Until the categorizer backend lands, every `/api/*` call fails, so the categorizer shows its error message and an empty board.
- [ ] Verify the pages in a browser and fix any console errors
  - Context: only a curl check (HTTP 200 on each asset) has been done so far.

---

# Features

## Feature: Portal shell

The landing page, the top bar and the navigation shared by every service, plus
the states and layouts that apply to all screens.

- **Status:** Prototyping
- **Prototype:** [`docs/prototypes/portal/v3.html`](prototypes/portal/v3.html), screens `#landing` and the top bar of every screen (v3 approved 2026-10-30, with amendments)

### Frontend

*Stage: Planned*

| ID | Type | Item | Spec | Status | Depends on | PRs |
|---|---|---|---|---|---|---|
| FE-01 | Story | [Top bar and navigation](stories/shell/FE-01-top-bar-navigation.feature) | [Approved](specs/shell/FE-01-top-bar-navigation.md) | Done | FE-23, BE-01 | [#23] |
| FE-02 | Story | [Categorizer service card](stories/landing/FE-02-categorizer-service-card.feature) | — | Draft | BE-02 |
| FE-19 | Story | Loading, error and session-expired states on every screen | — | Needs prototype | BE-23 |
| FE-20 | Story | Small screens, for every screen (v3 is desktop only) | — | Needs prototype | — |
| FE-23 | Task | Create the React app in `app/web/` (Vite, TypeScript, router, tokens, API client, Vitest) and move the static portal to `web/legacy/` (git-ignored, backed up to `~/odiservices-backups/`). Two PRs: scaffold, then API client | [Approved](specs/shell/FE-23-react-app.md) | Done | — | [#2], [#3], [#9], [#8] |

- FE-23: `app/portal/` was archived to `~/odiservices-backups/portal-pre-react-2026-10-30.tar.gz` and moved to `app/web/legacy/` (git-ignored, deleted after FE-13). Step 1 (scaffold) and step 2 (API client) are separate PRs. Done 2026-10-30. The spec's `make dev` and `make serve` checks need the backend, so they are verified in BE-17 and BE-01.

### Backend

*Stage: Planned*

| ID | Type | Item | Spec | Status | Depends on | PRs |
|---|---|---|---|---|---|---|
| BE-01 | Task | Serve the built React app from FastAPI (SPA fallback, `/api` JSON 404, headers) | [Approved](specs/shell/BE-01-serve-portal-pages.md) | Done | BE-17, BE-18, BE-21, FE-23 | [#21] |
| BE-02 | Task | Return a portal summary for the landing card | — | Draft | BE-23, BE-28, BE-29 |

Notes:
- FE-01: the two board checks (highlight on the board, board → "Categorizador") run on the placeholder board route `/categorizer/abc-123`. Their real-statement version is part of FE-06's verification, *Pending validation* with the owner's real statement. The real statement is never committed, turned into a fixture or kept in screenshots (`docs/TESTING_GUIDELINES.md`).
- BE-01: the board moves from `kanban/` into the portal as the categorizer service, behind the same Cloudflare Access app. Pages rely on Access at the edge in this slice; app-side JWT verification (BE-23) is required before BE-02 (BE-01 spec, Q1).
- BE-02: FE-02 shows the last statement period, how many transactions are pending review and how many statements were sent. Open question: does "pending review" count all statements or only the latest one?

---

## Feature: Statement upload and processing

Sending a card statement PDF, following its classification, and listing the
statements already sent (Categorizer home screen).

- **Status:** Prototyping
- **Prototype:** [`docs/prototypes/portal/v3.html`](prototypes/portal/v3.html), screen `#home` (v3 approved 2026-10-30, with amendments)

### Frontend

*Stage: Planned*

| ID | Type | Item | Spec | Status | Depends on | PRs |
|---|---|---|---|---|---|---|
| FE-03 | Story | [Upload a card statement](stories/categorizer-home/FE-03-upload-statement.feature) | — | Draft | BE-03 |
| FE-04 | Story | [List sent statements](stories/categorizer-home/FE-04-statement-list.feature) | — | Draft | BE-06, BE-07 |
| FE-05 | Story | [Retry a failed statement](stories/categorizer-home/FE-05-retry-failed-statement.feature) | — | Draft | BE-08 |
| FE-14 | Story | Follow processing until the board opens | — | Needs prototype | BE-07 |

### Backend

*Stage: Outline*

- **BE-03** Upload a statement PDF and run the extraction server-side
  - Context: `ask_pdf.py` is a local CLI today that writes to `outputs/`. To be product-ready, it should run server-side (upload PDF → Claude → import), with `ANTHROPIC_API_KEY` held on the server. The 10 MB limit shown in the prototype must be enforced here too.
- **BE-04** Do not persist uploaded PDFs, or store them encrypted
  - Context: card statements are sensitive financial documents. Decide on retention before building the upload.
- **BE-05** Import a statement from the extraction JSON
  - Context: no static data, so the result of the extraction must enter through the API. Validate it against the `ask_pdf.py` schema and check the transaction sum against `total_lanc_atuais`.
- **BE-06** List the current user's statements, newest first, paginated
  - Context: replaces the hardcoded `result-9.json` default in `serve.py`. FE-04 shows the name, the date sent, the status and the total, plus "Mostrar faturas anteriores".
- **BE-07** Track each statement's processing status and failure reason
  - Context: FE-04 shows "Classificando", "Concluída", "N para revisar" and "Falhou: <reason>". No current item stores this.
- **BE-08** Retry a failed extraction
  - Context: FE-05 "Tentar de novo" puts a failed statement back into classification without a new upload.
- **BE-09** Store the card name and last digits of each statement
  - Context: FE-06 shows "Cartão Exemplo final 0000". The `statements` table (BE-28) has no such field today.

---

## Feature: Statement board

Reviewing and fixing the classification of one statement: summary,
distribution, lanes, moves, confirmations, undo, export and delete.

- **Status:** Prototyping
- **Prototype:** [`docs/prototypes/portal/v3.html`](prototypes/portal/v3.html), screen `#board` (v3 approved 2026-10-30, with amendments)

### Frontend

*Stage: Planned*

| ID | Type | Item | Spec | Status | Depends on | PRs |
|---|---|---|---|---|---|---|
| FE-06 | Story | [Statement summary](stories/board/FE-06-statement-summary.feature) | — | Draft | BE-10, BE-09, FE-01 |
| FE-07 | Story | [Spending distribution](stories/board/FE-07-spending-distribution.feature) | — | Draft | BE-12 |
| FE-08 | Story | [Category lanes and cards](stories/board/FE-08-category-lanes.feature) | — | Draft | BE-10, BE-13, BE-16 |
| FE-09 | Story | [Move a transaction by dragging](stories/board/FE-09-move-by-drag.feature) | — | Draft | BE-11 |
| FE-10 | Story | [Confirm a doubtful transaction](stories/board/FE-10-confirm-doubtful-transaction.feature) | — | Draft | BE-11 |
| FE-11 | Story | [Filter by description](stories/board/FE-11-filter-by-description.feature) | — | Draft | — |
| FE-12 | Story | [Undo the last change](stories/board/FE-12-undo-last-change.feature) | — | Draft | BE-11 |
| FE-13 | Story | [Export as JSON](stories/board/FE-13-export-json.feature) | — | Draft | BE-14 |
| FE-15 | Story | Review doubts one by one ("Revisar 2 dúvidas", key `R`) | — | Needs prototype | BE-11 |
| FE-16 | Story | Move with the keyboard and multi-select | — | Needs prototype | BE-11 |
| FE-17 | Story | Shortcuts help and undo all changes | — | Needs prototype | BE-11 |
| FE-18 | Story | Delete a statement with confirmation | — | Needs prototype | BE-15 |
| FE-21 | Task | Decide whether localStorage (`categorizador-kanban-v1`) stays as an offline cache | — | Draft | — |
| FE-22 | Task | Retire `build_standalone.py`, or keep it only as an offline export | — | Draft | — |

- FE-06: its verification includes FE-01's two board checks on a real statement's board (highlight on "Categorizador", and board → "Categorizador"), *Pending validation* with the owner's real statement.

### Backend

*Stage: Outline*

- **BE-10** Get one statement with its transactions
  - Context: replaces `/data/result.json` and `/data/extract.json`. It returns one merged shape so the frontend no longer joins two files.
- **BE-11** Update a transaction's category and reviewed flag
  - Context: this is the core board action (drag a card, confirm a doubt, undo). It replaces the localStorage edits so changes persist across browsers.
- **BE-12** Return a per-category summary for a statement
  - Context: feeds the distribution bar. Computing the totals on the server keeps them consistent with the database.
- **BE-13** Record whether a transaction's category was changed by the user
  - Context: FE-08 shows "Movido por você" on cards the user moved. It needs the original category, or a flag.
- **BE-14** Export a statement
  - Context: FE-13 "Exportar JSON". Decide between a server endpoint and an export built in the browser.
- **BE-15** Delete a statement and its transactions
  - Context: FE-18 "Excluir fatura". Decide between a hard delete and a soft delete.
- **BE-16** Provide display labels for the categories
  - Context: the database stores `FORNECEDOR`, but the UI shows "Fornecedor". Decide whether the mapping lives in the API or in the frontend.

---

# Platform

## Project foundation

### Backend

*Stage: Planned*

| ID | Type | Item | Spec | Status | Depends on | PRs |
|---|---|---|---|---|---|---|
| BE-17 | Task | Create the FastAPI project in `app/api/` (monorepo root `app/`), replacing `kanban/` | [Approved](specs/foundation/BE-17-fastapi-project.md) | Done | — | [#10] |
| BE-18 | Task | Load settings from environment variables | [Approved](specs/foundation/BE-18-settings.md) | Done | BE-17 | [#13] |
| BE-19 | Task | Pin runtime dependencies in `requirements.txt` | [Approved](specs/foundation/BE-19-pinned-requirements.md) | Done | BE-17 | [#14] |
| BE-20 | Task | Expose a `/healthz` endpoint | [Approved](specs/foundation/BE-20-healthz.md) | Done | BE-17 | [#16] |
| BE-21 | Task | Log requests without PII | [Approved](specs/foundation/BE-21-request-log.md) | Done | BE-17, BE-18, BE-20 | [#18] |
| BE-22 | Task | Publish OpenAPI documentation behind Access | — | Draft | BE-17, BE-23 |
| BE-32 | Task | Add a Content-Security-Policy to every response (BE-01 spec, Q3, confirmed by the owner 2026-10-30). Due before OPS-03, preferably before FE-03 | — | Draft | BE-01 |

Notes:
- BE-17: the portal will house multiple client services, and the categorizer board is the first one. The owner chose FastAPI. `kanban/serve.py` is a 54-line static file server, so nothing of it is reused. The spec proposes `app/` as the project root instead of a top-level `portal/` (Q1). `kanban/` was backed up to `~/odiservices-backups/kanban-pre-fastapi-2026-10-30.tar.gz` and deleted. Done 2026-10-30. The `/healthz` check waits for BE-20.
- BE-18: Supabase and Cloudflare Access values differ per environment and must never be committed. `.env.example` lists the variable names only.
- BE-19: the owner requested it. Exact pins give reproducible builds on Lightsail.
- BE-20: used by the Docker healthcheck and the Lightsail or uptime monitoring. It needs no auth.
- BE-21: transaction descriptions and user emails are personal and financial data. Logs carry ids, status and timing only.
- BE-22: the portal will integrate other services. FastAPI generates this.

**First slice** (needed by FE-01): BE-17 → BE-18, BE-19 → BE-20, BE-21 → BE-01, with FE-23 in parallel, then FE-01.
The owner authorized creating the Python venv (uv) and installing the pinned Python and Node dependencies for this slice (2026-10-30).
Monorepo layout and React: `docs/proposals/monorepo-and-react.md` (approved 2026-10-30).

## Authentication (Cloudflare Access)

### Backend

*Stage: Outline*

- **BE-23** Verify the Cloudflare Access JWT on every protected request
  - Context: the owner defined Cloudflare Access as the auth layer. Verify the `Cf-Access-Jwt-Assertion` header against the team's certs and the application AUD. `app/src/auth/access-jwt.ts` (in the backup) already does this in TypeScript and is a reference.
- **BE-24** Resolve the Access identity to a `users` row
  - Context: there is a single user for now, but every record should belong to a user. Create the row on first login, keyed by the Access subject.
- **BE-25** Provide a local development auth bypass
  - Context: Cloudflare Access is not present locally. A setting that is off by default in production injects a fixed dev user.

## Database (Supabase)

### Backend

*Stage: Outline*

- **BE-26** Use Supabase as the backend database
  - Context: it stores the extracted card statement data, as the owner defined. FastAPI is the only client, and the service-role key stays on the server and never reaches the browser.
- **BE-27** Create the `users` table
  - Context: there are no multiple users yet, but the owner wants the table now and roles later. Keep it minimal (id, Access subject, email, timestamps) so a `roles` / `user_roles` table can be added without reworking it.
- **BE-28** Create the `statements` table (one row per card statement / fatura)
  - Context: each extraction yields one statement with `total_lanc_atuais`. It belongs to a user and is used to validate the sum of its transactions. Feature items add columns to it (BE-07, BE-09).
- **BE-29** Create the `transactions` table (lançamentos)
  - Context: the columns mirror `ask_pdf.py` `SCHEMA`: item number within the statement, `secao` (compras/internacional/produtos), `data` (dd/mm text as printed), `descricao`, `valor` (numeric, BRL), `categoria`, `duvida`. It also needs `revisado` and `updated_at`, which today live in the board's localStorage. BE-13 adds the original category.
- **BE-30** Model categories as a constrained set
  - Context: the 10 fixed categories (FORNECEDOR … OUTROS) are duplicated in `ask_pdf.py` and `kanban/app.js`. Make the database the single source of truth through an enum or lookup table.
- **BE-31** Version schema changes as SQL migrations
  - Context: they must be reproducible across the dev and prod Supabase projects. Enable RLS with no anon access, since only the backend talks to Supabase.

## Packaging and deployment (AWS Lightsail)

### Infrastructure

*Stage: Outline*

- **OPS-01** Write a Dockerfile for the portal
  - Context: the owner requested it. Use a slim pinned base and a non-root user. The build context is `app/`, built in two stages (`docs/proposals/monorepo-and-react.md`), and `.dockerignore` keeps `.env`, `input/` PDFs and `outputs/` out of the image.
- **OPS-02** Write a docker-compose file for local testing
  - Context: the owner requested it to test the setup locally. It points at a dev Supabase project, never production.
- **OPS-03** Deploy to AWS Lightsail
  - Context: the owner chose the host. `app/DEPRECATED.md` records a previous Lightsail setup that used systemd rather than Compose, so decide between a container and systemd for this service.
- **OPS-04** Put Cloudflare in front of the Lightsail instance
  - Context: Access only protects traffic that passes through Cloudflare. Use a Cloudflare Tunnel, or a firewall restricted to Cloudflare IPs, so the origin cannot be reached directly and Access cannot be bypassed.
- **OPS-05** Manage secrets on the host
  - Context: the Supabase service-role key, the Access AUD and the Anthropic key must live outside the repo and the image, either as Lightsail environment variables or a root-only env file.

## Quality

### Quality

*Stage: Outline*

- **QA-01** Keep the canonical fictitious fixture and the shared test helpers
  - Context: the pytest harness itself is created by BE-17 and each item brings its own unit tests (`docs/TESTING_GUIDELINES.md`). QA-01 now covers `app/fixtures/` (the v3 statement: 17 transactions, R$ 11.906,35) and helpers such as fake Access tokens for BE-23 tests. Never use real lançamentos as test data.
- **QA-02** Add a CI check for tests and lint
  - Context: keeps the backlog items mergeable one at a time as each is planned and implemented.
- **QA-03** Run the Gherkin stories as automated tests
  - Context: the frontend stories in `docs/stories/` are written to be executable. The suggested setup is `pytest-bdd` with Playwright for Python, against the portal served locally with fictitious fixtures.

---

## Appendix: migration from the previous structure

The backlog was reorganized on 2026-10-30 from technical sections into
features and platform. This table maps each item of the previous structure to
its new place.

| Previous section › item | New place |
|---|---|
| Bootstrap › all items | Bootstrap (unchanged) |
| Project foundation › all items | Platform › Project foundation (BE-17 to BE-21) |
| Authentication › all items | Platform › Authentication (BE-23 to BE-25) |
| Database › all items | Platform › Database (BE-26 to BE-31) |
| Categorizer API › Import a statement | Statement upload and processing › BE-05 |
| Categorizer API › List the user's statements | Statement upload and processing › BE-06 |
| Categorizer API › Get one statement | Statement board › BE-10 |
| Categorizer API › Update category and reviewed flag | Statement board › BE-11 |
| Categorizer API › Per-category summary | Statement board › BE-12 |
| Categorizer API › Publish OpenAPI documentation | Platform › Project foundation › BE-22 |
| Board frontend › Serve the board from FastAPI | Portal shell › BE-01 |
| Board frontend › Load data from the API | Covered by FE-06 to FE-08, which depend on BE-10 and BE-12 |
| Board frontend › Persist edits through the API | Covered by FE-09, FE-10 and FE-12 (scenarios check the change survives a reload); the cache decision is FE-21 |
| Board frontend › Decide the future of `build_standalone.py` | Statement board › FE-22 |
| Extraction pipeline › Trigger extraction from the portal | Statement upload and processing › BE-03 |
| Extraction pipeline › Do not persist uploaded PDFs | Statement upload and processing › BE-04 |
| Packaging and deployment › all items | Platform › Packaging and deployment (OPS-01 to OPS-05) |
| Quality › all items | Platform › Quality (QA-01, QA-02) |

New items that came from writing the stories: BE-02, BE-07, BE-08, BE-09, BE-13,
BE-14, BE-15, BE-16 and QA-03. Added later: BE-32 (from the BE-01 spec).

<!-- PR links: one definition per PR listed in the PRs column, sorted by number. -->
[#2]: https://github.com/arielantony/odiservices/pull/2
[#3]: https://github.com/arielantony/odiservices/pull/3
[#8]: https://github.com/arielantony/odiservices/pull/8
[#9]: https://github.com/arielantony/odiservices/pull/9
[#10]: https://github.com/arielantony/odiservices/pull/10
[#13]: https://github.com/arielantony/odiservices/pull/13
[#14]: https://github.com/arielantony/odiservices/pull/14
[#16]: https://github.com/arielantony/odiservices/pull/16
[#18]: https://github.com/arielantony/odiservices/pull/18
[#21]: https://github.com/arielantony/odiservices/pull/21
[#23]: https://github.com/arielantony/odiservices/pull/23
