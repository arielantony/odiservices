# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

OdiServices Portal is Odisseia's internal portal. Its first service is the
categorizer: it reads a credit card statement (PDF), extracts the
transactions and lets the finance team review their categories on a board.

The documents in `docs/` are the source of truth. Read the ones that apply
before changing anything:

| Document | What it governs |
|---|---|
| `docs/CONSTITUTION.md` | Language, HTML prototype before any frontend change, pull requests |
| `docs/BACKLOG.md` | Items, status, dependencies and the order of work |
| `docs/specs/README.md` | What a spec is and how it is approved |
| `docs/specs/<area>/<ID>-*.md` | How each item is built |
| `docs/FRONTEND_GUIDELINES.md` | Brief → prototype → stories → spec → implementation |
| `docs/BACKEND_GUIDELINES.md` | Need → spec with the contract → implementation, and the backend conventions (errors, settings, logging, auth, data) |
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
- **Every verification check runs when the item merges,** with only the item
  and its dependencies. A check that needs a later item belongs in that
  item's spec; if you find one, the spec is wrong (stop and propose the
  fix). Only *Pending validation* checks (the owner's real data) may stay
  unchecked in a PR.
- **Every item ends in a pull request** (`docs/CONSTITUTION.md`, Article 6),
  opened with `gh pr create`. Under 500 changed lines (lockfiles and
  binaries excluded). If an item would be larger, propose the steps in its
  spec before coding. Never push to `main` and never merge; the owner
  reviews and merges.
- **Branches.**
  - An item with steps gets a feature branch `feature/<id>-<slug>` from
    `origin/main`.
  - Each step is a branch `<type>/<id>-step-<n>-<slug>` from the latest
    feature branch, and its PR targets the feature branch.
  - When all steps are merged, a final PR takes the feature branch to
    `main`.
  - A single-step item, or a change that isn't a backlog item, branches from
    `origin/main` and targets `main`.
  - Never stack a branch on another step's branch, and never rebase or
    force-push a feature branch.
  - Bring `main` into a feature branch through a PR. While the feature
    branch has no commits of its own, fast-forward it instead, with no PR:
    `git push origin origin/main:<feature-branch>`.
  - Right after `gh pr create`, push a commit `docs: link #N in backlog`
    that adds `[#N]` to the item's PRs column and `[#N]: <PR URL>` to the
    PR links block at the end of `docs/BACKLOG.md`.
- **Worktrees.** Work on every branch in its own worktree:
  `git fetch origin && git worktree add .worktrees/<branch> -b <branch> origin/<base>`.
  Run all commands inside it. After a merge, `scripts/after-merge.sh`
  removes merged worktrees and their local branches and rebases the local
  `main`; the hooks in `.claude/settings.json` run it after `gh pr merge`
  and when a prompt mentions a merge or `#N`.
- **The PR description follows `.github/pull_request_template.md`.** Its
  sections are What changed, How to test, Tests and Verification. Update
  the item's status in `docs/BACKLOG.md` in the same PR. Don't start the
  next item until the owner says so.

## Stack and commands

- `app/` is a monorepo: `api/` (FastAPI, Python 3.14), `web/` (React, Vite,
  TypeScript), `fixtures/` (shared fictitious test data), one `Makefile`.
- **Python:** a uv-managed venv in `app/api/.venv`. Dependencies are pinned
  with `==` in `requirements*.txt`, compiled from `requirements*.in`
  (BE-19). `make dev`, `serve` and `test-api` create the venv and sync it
  when a requirements file changes (`make setup-api` does it alone), so every
  worktree builds its own.
- **Node:** version 24 through nvm (`app/web/.nvmrc`). This machine defaults
  to Node 25, so run `nvm use` first.
- **Yarn 4** through corepack (`corepack enable`). Never npm or pnpm.
  `yarn install --immutable`, exact versions, `nodeLinker: node-modules`.
- **Installing packages** is authorized only for the packages a Ready item's
  spec lists. Ask before installing anything else, including global tools.
- `app/Makefile` is the entry point; run it from `app/`. FE-23 created
  `setup-web`, `build-web`, `test-web` and `test`, and these work today.
  `dev` and `test-api` already exist, but they target `app/api/`, which
  doesn't exist until BE-17. `serve` comes with BE-17.
- To run a single web test: `cd app/web && nvm use && yarn test --run
  src/app/router.test.tsx`. Add `-t "<name>"` to run one case.

## Architecture

- **Web (`app/web/`)**
  - `src/app/` holds the entry router and layout (`router.tsx`,
    `Layout.tsx`).
  - Each service gets a folder under `src/features/<service>/`, for
    example `landing/` and `categorizer/`.
  - The brand tokens are in `src/styles/tokens.css`.
  - Tests are `*.test.ts(x)` files placed next to the code they test.
  - Vitest is configured inside `vite.config.ts`: jsdom, globals, and the
    setup file `src/test/setup.ts`.
- **Dev setup.** Vite serves on 127.0.0.1:5173 and proxies `/api` and
  `/healthz` to uvicorn on 127.0.0.1:8000. In prod, FastAPI serves
  `web/dist/` with an SPA fallback (BE-01).
- **Routes.** `/`, `/categorizer` and `/categorizer/:id`. The categorizer
  screens are placeholders until FE-03 to FE-13 migrate them, per option A
  in the monorepo proposal.
- **`project-tracker/`** builds a visual status page from
  `docs/BACKLOG.md`. Run `python3 project-tracker/generate.py --open`; the
  output goes to `project-tracker/dist/`. It reads the backlog and never
  writes to it, so changes to the backlog's table format, headings or ID
  prefixes have to be mirrored in `generate.py`.

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

- The vanilla categorizer moves to `app/web/legacy/` (FE-23), which is
  git-ignored and backed up first. It is a behavior reference only: it is
  not served and is deleted after FE-13.
- `kanban/` is removed by BE-17, after the backup tarball in
  `~/odiservices-backups/` described in its spec.
- The standard screen width is 1360 px. FE-01 is checked at 1280 px and
  1360 px.
- `ask_pdf.py` at the repo root moves into `app/api/` only when BE-03 needs
  it.
- CSP is BE-32, a separate item. BE-01 doesn't include it.
