# Proposal — Monorepo layout and React

| | |
|---|---|
| **Status** | Approved, 2026-10-30. R4 and R5 were set by the owner. R9: option A |
| **Date** | 2026-10-30 |
| **Affects** | BE-17, BE-01, FE-01, OPS-01, and every later frontend story |

**Approved on 2026-10-30.** The specs BE-17, BE-01 and FE-01 were updated, and FE-23 was written (section 4).

The owner decided that `app/` is a monorepo holding the backend and the
frontend (BE-17, Q1), and asked whether React can be adopted now so that the
UI is built from components. This proposal answers both points. Nothing changes
in the specs until it is approved.

## 1. Can we adopt React now?

Yes. This is the cheapest moment to do it. The only frontend code today is the
static landing and the vanilla categorizer, which has about 1,000 lines in
`shell.js` and `board.js`. Every screen will be redesigned anyway by FE-01 to
FE-20.

What changes:

- **A build step.** The bootstrap dropped `package.json` on purpose. React
  brings it back, together with Node and a lockfile.
- **What FastAPI serves.** It serves the built files (`web/dist/`), not the
  source files.
- **Prototypes don't change.** They stay single HTML files with no build
  (`docs/CONSTITUTION.md`, Article 3). Only `app/` gets a build.

## 2. Monorepo layout

The layout is flat. `app/` is already the root, so an `apps/` level would only
add depth.

```
app/
├── Makefile            # one entry point: dev, test, lint, build
├── README.md           # how to run everything
├── .env.example
├── fixtures/           # fictitious data shared by api and web tests
│   └── statement-example-2026-09.json
├── api/                # FastAPI (Python 3.14)
│   ├── requirements.in / requirements.txt
│   ├── requirements-dev.in / requirements-dev.txt
│   ├── server/         # Python package: main.py, settings.py, request_log.py, routes/
│   └── tests/
└── web/                # React + Vite
    ├── package.json / yarn.lock / .yarnrc.yml / .nvmrc
    ├── index.html
    ├── src/
    │   ├── app/        # entry point, router
    │   ├── components/ # shared components: TopBar, Button, …
    │   ├── features/   # one folder per service: landing/, categorizer/
    │   ├── styles/     # tokens.css
    │   └── assets/     # logo
    └── tests/          # or *.test.tsx next to each component
```

Notes:

- **No `packages/` folder yet.** It is created only when code has a second
  consumer. For example, TypeScript types generated from the OpenAPI schema
  (BE-22) would be used by `web/` and by another service.
- **No Nx or Turborepo.** At this size, a Makefile is enough.
- **`ask_pdf.py`** (at the repo root) moves into `api/` when BE-03 needs the
  extraction.
- **OPS-01** becomes a multi-stage Docker build. A Node stage runs
  `corepack enable && yarn install --immutable && yarn build` on `node:24-slim`. A slim Python stage copies `web/dist/` and runs
  `api/`. The final image has no Node.
- **Development.** In dev, Vite serves `web/` with hot reload and proxies
  `/api` and `/healthz` to uvicorn. `make dev` starts both. In prod, FastAPI
  serves `web/dist/`.

## 3. Sub-decisions

Each has a recommended option. Versions were checked on the npm registry on
2026-10-30, and the lockfile decides the exact pins.

| # | Decision | Recommendation | Why |
|---|---|---|---|
| R1 | Language | **TypeScript** (7.0) | Typed props on components, and API types can be generated from OpenAPI later |
| R2 | Bundler | **Vite** (8.3) with `@vitejs/plugin-react` | The standard for a React SPA, no server framework needed |
| R3 | Routing | **React Router** (8.5), in declarative mode | Three routes (`/`, `/categorizer`, `/categorizer/:id`). The board gets its own URL, which also simplifies FE-01's board scenario |
| R4 | Package manager | **Yarn 4** (4.18 today), enabled with `corepack enable` and pinned in `packageManager` in `package.json`. `nodeLinker: node-modules` in `.yarnrc.yml` | **Owner's decision (2026-10-30).** The `node-modules` linker avoids Plug'n'Play friction with Vite, Vitest and editors |
| R5 | Node | **24 LTS** through **nvm**: `web/.nvmrc` contains `24`, and `engines.node` is `>=24 <25` | **Owner's decision (2026-10-30).** The local machine runs 25 by default, so `nvm use` (or `nvm install 24`) is the first step, and the Makefile targets call it |
| R6 | Lockfile | `yarn.lock` committed, `yarn install --immutable` in CI and Docker, exact versions (`defaultSemverRangePrefix: ""`) | The JS counterpart of BE-19 |
| R7 | Styling | Plain CSS with the brand tokens (`tokens.css`) and CSS Modules per component | No UI library, because the Odisseia brand is custom and the prototypes already define the CSS |
| R8 | Frontend tests | **Vitest** (5.0) and **Testing Library** (16.3) | Same toolchain as Vite (see `docs/TESTING_GUIDELINES.md`) |

### R9 — What happens to the vanilla categorizer

This is the decision that matters most. FE-01 must not silently grow into a
rewrite of the categorizer.

- **Option A (recommended, chosen): migrate per story.**
  - FE-01 creates the React app with the top bar, the landing route and the
    categorizer route.
  - The categorizer route shows only the top bar and a placeholder, "Em
    migração", until FE-03 to FE-13 rebuild its screens in React, one story at
    a time.
  - The vanilla code stays in the repo (`web/legacy/`) as a behavior
    reference, is not served, and is deleted when FE-13 is done.
  - Cost: the categorizer is unusable until FE-03 lands. Its backend doesn't
    exist yet (BE-03 to BE-12), so nothing that works today is lost.
- **Option B: keep the vanilla page alive.** It is served as a separate page
  with the top bar repeated in its HTML, alongside the React app, until FE-13.
  Cost: two frontends and two top bars to maintain, and FE-01 is verified
  twice.

## 4. What changes in the specs once this is approved

| Spec | Section | Change |
|---|---|---|
| BE-17 | 3.1 Layout | `app/api/server/` instead of `app/server/`; run from `app/api/` |
| BE-17 | 3.4 Run command | `make dev` (uvicorn and Vite) and `make serve` (uvicorn serving `web/dist/`) |
| BE-01 | 3.1 and 3.2 | Mount `web/dist/` instead of `portal/`. An SPA fallback returns `index.html` for unknown paths that are not `/api/*`, `/healthz` or files. `/categorizer` without the trailing slash is handled by the router, not by a redirect |
| BE-01 | Q2 | Superseded by this proposal |
| FE-01 | 2 and 5 | A `TopBar` component that receives the current section, inside the router layout. No duplicated markup |
| FE-01 | 4.2 | The board gets its own URL (`/categorizer/:id`). "Categorizador" navigates in the client, with no reload |
| FE-01 | 7 | Unit tests in Vitest, plus the browser checks |
| New | — | A new task, **FE-23** "Create the React app (Vite, TypeScript, router, tokens, test setup)", which FE-01 depends on |
