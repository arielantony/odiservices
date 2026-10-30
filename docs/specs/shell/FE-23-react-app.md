# Spec — FE-23 Create the React app

| | |
|---|---|
| **Backlog** | Portal shell › Frontend › FE-23 (Task) |
| **Needed by** | FE-01 and every later frontend story |
| **Depends on** | — (BE-01 is only needed for `make serve`) |
| **Spec status** | Approved, 2026-10-30. Updated the same day: `legacy/` stays out of git, and the item ships in two PRs (3.8) |
| **Date** | 2026-10-30 |

## 1. Goal

Create `app/web/`, a React app built with Vite. It has the routes, the layout,
the brand tokens, an API client and the test setup that every frontend story
builds on. It replaces the static portal, following the approved proposal
(`docs/proposals/monorepo-and-react.md`, option A).

## 2. Scope

**In scope:**

- Toolchain: Node 24 (nvm), Yarn 4 (corepack), Vite, TypeScript, React,
  React Router, Vitest and Testing Library.
- Routes and layout, with temporary placeholders on each route.
- `tokens.css` and the font link.
- An API client with the same error contract as the current `api.js`.
- Moving the static portal to `web/legacy/`, kept out of git (3.2).
- The web targets in the Makefile.

**Out of scope:**

| Excluded | Covered by |
|---|---|
| Top bar | FE-01 |
| Real screens | FE-02 to FE-20 |
| Serving the build | BE-01 |
| Lint and CI | QA-02 |
| Gherkin runner | QA-03 |

## 3. Design

### 3.1 Toolchain

| Item | Value |
|---|---|
| Node | `web/.nvmrc` = `24`, and `engines.node` = `>=24 <25`. Every Makefile web target runs through `nvm use` |
| Yarn | `corepack enable`, and `packageManager: "yarn@4.x.y"` pinned in `package.json` |
| `.yarnrc.yml` | `nodeLinker: node-modules`, `defaultSemverRangePrefix: ""` (exact versions), `enableTelemetry: false` |
| Lockfile | `yarn.lock` is committed. Installs use `yarn install --immutable` |
| Language | TypeScript, `strict: true` |

Dependencies are exact versions, checked on the npm registry on 2026-10-30.
The lockfile decides the final pins.

- **Runtime:** `react` and `react-dom` 19.3, `react-router` 8.5.
- **Dev:** `vite` 8.3, `@vitejs/plugin-react` 6.1, `typescript` 7.0,
  `vitest` 5.0, `@testing-library/react` 16.3,
  `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`.

### 3.2 Layout

```
app/web/
├── .nvmrc  .yarnrc.yml  package.json  yarn.lock  tsconfig.json  vite.config.ts
├── index.html                 # lang="pt-BR", Montserrat + Gilda Display link (FE-01, Q3)
├── legacy/                    # the former app/portal/: git-ignored, not served, deleted after FE-13
└── src/
    ├── main.tsx
    ├── app/
    │   ├── router.tsx         # routes, see 3.3
    │   ├── Layout.tsx         # FE-01 adds <TopBar/> here; renders <main><Outlet/></main>
    │   └── NotFound.tsx
    ├── api/
    │   └── client.ts          # ApiError contract, see 3.5
    ├── components/            # shared components (TopBar comes with FE-01)
    ├── features/
    │   ├── landing/LandingPage.tsx
    │   └── categorizer/CategorizerHomePage.tsx, BoardPage.tsx
    ├── styles/
    │   ├── tokens.css         # 3.4
    │   └── global.css         # reset, body font, paper background
    └── test/
        └── setup.ts           # jest-dom matchers
```

`app/portal/` moves, unchanged, to `app/web/legacy/`. It is a behavior
reference only, so it never enters git (owner's decision, 2026-10-30):

1. archive `app/portal/` to `~/odiservices-backups/portal-pre-react-2026-10-30.tar.gz`
   (the same place as the bootstrap backup);
2. move it to `app/web/legacy/`, which the root `.gitignore` already ignores;
3. record both steps in the backlog.

Committing it would add about 1,400 lines of old code to a PR
(`docs/CONSTITUTION.md`, Article 6) without anything to review.

### 3.3 Routes

| Path | Element | Until |
|---|---|---|
| `/` | `LandingPage`: a placeholder with the text "Em migração" | FE-02 |
| `/categorizer` | `CategorizerHomePage`: placeholder | FE-03 |
| `/categorizer/:statementId` | `BoardPage`: placeholder | FE-06 |
| `*` | `NotFound`: "Página não encontrada." with a link "Voltar ao início" | Designed in v4 |

The router is created with `createBrowserRouter`. Every route is a child of
`Layout`.

The placeholders are temporary scaffolding and are not designed. Each one is
a single paragraph with the text "Em migração", on the paper background, with
no data. The 404 text is the only new interface copy. It is listed as a v4
gap ("not found" state) in `docs/stories/README.md`.

### 3.4 Tokens and global styles

`tokens.css` declares the v3 tokens on `:root`:

| Group | Tokens |
|---|---|
| Brand colors | `--navy #081B59`, `--ink #0F1F33`, `--orange #EE5E27`, `--amber #F79829`, `--peach #F6D4B1`, `--paper #F5F4F2` |
| UI colors | `--muted #4F5B70`, `--line #E2DED8`, `--amber-bg #FDE9CC`, `--amber-ink #6B3A00`, `--pos #2F7A55` |
| Fonts | `--font-sans: Montserrat, system-ui, sans-serif` and `--font-display: "Gilda Display", serif` |

`global.css` contains:

- `box-sizing: border-box`;
- `body` with margin 0, `--font-sans`, `--paper` as the background and
  `--ink` as the text color;
- `font-variant-numeric: tabular-nums`.

Components never hardcode a color that has a token.

### 3.5 API client

`src/api/client.ts` ports the request and error logic of the current `api.js`,
so the backend contract stays the same:

- **Errors:** `ApiError { kind: "http" | "network", status, code, message, version? }`.
- **Redirects:** `redirect: "manual"`, and an opaque redirect becomes
  `401 unauthenticated` ("Sessão expirada. Entre novamente").
- **Error body:** the `ErrorBody` format is `{"error": {"code", "message"}}`.
- **URLs:** no statement data or file names in URLs.

FE-23 ports only the generic `request()` and `ApiError`. The per-endpoint
methods arrive with their stories.

### 3.6 Vite and dev server

- **Dev server:** port 5173, bound to `127.0.0.1`. `server.proxy` sends
  `/api` and `/healthz` to `http://127.0.0.1:8000`.
- **Build:** output in `web/dist/`, which is git-ignored, with hashed assets
  in `dist/assets/`.
- **Tests:** `test.environment: "jsdom"` and `test.setupFiles:
  "src/test/setup.ts"`.

### 3.7 Makefile (in `app/`)

| Target | Runs |
|---|---|
| `make setup-web` | `corepack enable`, `nvm install` (reads `.nvmrc`), `yarn install --immutable` |
| `make dev` | uvicorn (BE-17) and `yarn dev`, side by side |
| `make build-web` | `yarn build` |
| `make test-web` | `yarn test --run` |
| `make test` | `test-api` and `test-web` |

### 3.8 Pull requests

The item is delivered in two steps, each a PR under 500 changed lines
(`yarn.lock` excluded), each leaving the app working and its tests passing:

| Step | Contents | Tests |
|---|---|---|
| 1. App scaffold | Toolchain (3.1), layout and routes (3.2, 3.3), tokens and global styles (3.4), Vite (3.6), Makefile targets (3.7), the `legacy/` move | `router.test.tsx`, `tokens.test.ts` |
| 2. API client | `src/api/client.ts` (3.5) | `client.test.ts` |

If step 1 still goes over the limit, the tokens and global styles move into
a step of their own, before the API client.

## 4. Verification

| Check | Expected |
|---|---|
| `make setup-web` on a clean clone | Installs without changing `yarn.lock` |
| `node --version` inside the targets | v24.x |
| `make dev`, open `http://127.0.0.1:5173/` | Landing placeholder, no console errors |
| Visit `/categorizer` and `/categorizer/abc-123` directly | The right placeholder for each |
| `/nao-existe` | "Página não encontrada." |
| `make build-web && make serve`, open `http://127.0.0.1:8000/categorizer` | The same as in dev, served by FastAPI (BE-01) |
| `make test-web` | All green |
| `document.fonts.check('500 14px Montserrat')` | true |
| `app/portal/` | Gone. `app/web/legacy/` holds the same files, `git status` doesn't list it, `dist/` doesn't contain it, and the backup tarball lists its files |

## 5. Tests

These run with Vitest and Testing Library. The client tests use a fetch stub
that returns fictitious responses and never calls a server:

| File | Test | Asserts |
|---|---|---|
| `app/router.test.tsx` | `renders each route inside the layout` | `/`, `/categorizer` and `/categorizer/abc-123` each render their placeholder inside `main` |
| | `unknown path renders not found` | `/nao-existe` shows "Página não encontrada." and a link to `/` |
| `api/client.test.ts` | `network failure` | A rejected fetch gives `ApiError{kind:"network", status:0, code:"network"}` |
| | `error body is parsed` | 404 `{"error":{"code":"not_found","message":"Recurso não encontrado."}}` gives `code` `not_found` and that message |
| | `error without body` | 500 with no JSON gives `code` `http_500` |
| | `opaque redirect means session expired` | Gives `status` 401 and `code` `unauthenticated` |
| | `conflict carries version` | 409 with `error.version: 3` gives `version` 3 |
| | `invalid JSON on 2xx` | Gives `code` `bad_response` |
| `styles/tokens.test.ts` | `tokens match the brand` | `tokens.css` declares every token in 3.4 with the listed values |

## 6. Open questions

Answers (2026-10-30):

- **Q1:** accepted. "Em migração" is temporary scaffolding.
- **Q2:** accepted. No deploy to Lightsail until FE-03 to FE-05 are Done.

1. **Placeholder text:** "Em migração" is not designed copy.
   *Recommendation:* accept it as temporary scaffolding. It never reaches
   production without at least FE-02 and FE-03, because OPS-03 deploys only
   after those stories.
2. **Deploying in the middle of the migration:** With option A, the
   categorizer is unusable between FE-23 and FE-03.
   *Recommendation:* don't deploy to Lightsail until FE-03 to FE-05 are Done.
   Nothing is in production today.
