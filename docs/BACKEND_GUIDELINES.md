# Backend Guidelines — OdiServices

How we create or extend the portal's backend (`app/api/`), step by step, and
the conventions every backend item follows. It applies to any person or AI
agent working on the backend. If it ever disagrees with
`docs/CONSTITUTION.md`, the constitution wins.

The conventions below come from the approved specs BE-17 to BE-21 and BE-01.
When one of them changes, the spec that introduced it and this guide change
together.

## The process at a glance

| # | Step | Who | Output |
|---|---|---|---|
| 1 | Need | Product owner, or a frontend story | A backlog item with a short context line |
| 2 | Clarifying questions | Agent | Up to 4 questions with recommended options, or a list of assumptions |
| 3 | Spec | Agent, approved by the product owner | One spec per item in `docs/specs/`, with the contract |
| 4 | Implementation | Agent or developer | Code and tests in `app/api/`, in one or more pull requests |
| 5 | Done | Product owner | Merged PR, tests passing, verification checked |

The backend has no prototype. Its equivalent is the **contract** in the spec:
what the outside world can call and what it gets back. Nothing in `app/`
changes before the spec is approved.

## Step 1 — Need

A backend item starts in one of two ways:

- **From the product owner:** a platform need, such as auth, the database or
  deployment. It enters `docs/BACKLOG.md` as an Outline bullet with a context
  line.
- **From a frontend story:** a screen needs data or an action. The frontend
  spec names the backend item it depends on, and the backlog records that
  dependency.

When an area starts its technical design, it moves from Outline to Planned,
following the rules in `docs/BACKLOG.md`.

## Step 2 — Clarifying questions

The same rules as the frontend (`docs/FRONTEND_GUIDELINES.md`, step 2): up to
4 questions in one message, each with a recommended option, and only about
what changes the design. A question that gets no answer becomes an assumption
and is recorded in the spec.

Good backend topics: what data the endpoint exposes and to whom, what happens
on failure or retry, limits (file size, number of items), and anything that
touches money, personal data or a third-party service.

## Step 3 — Spec

The spec follows `docs/specs/README.md`. For a backend item, the Design
section contains the **contract**:

- **Routes:** method, path, and who may call it.
- **Payloads:** request and response bodies, with field types and an example
  using fictitious data.
- **Errors:** every status the route can return, with its `code` and pt-BR
  `message` (see "Errors" below).
- **Settings:** new environment variables, with type and default.
- **Data:** tables or columns it reads or writes.
- **Files:** the changes per file.

If a frontend story depends on the item, the backend spec defines the
contract, and the frontend spec links to it instead of repeating it. A change
to the contract after approval means both specs are updated and re-approved.

If the item would change more than 500 lines, the spec lists the steps, one
pull request each (`docs/CONSTITUTION.md`, Article 6).

Before asking for approval, check the Verification section against the
Depends on line: every check runs with only this item and its dependencies,
when the item merges (`docs/specs/README.md`, section 4). Move any check that
needs a later item to that item's spec.

## Step 4 — Implementation

- Implement only **Ready** items, exactly as the spec says, with the tests
  its Tests section lists.
- Each item or step is one branch and one pull request, opened with
  `gh pr create`, under 500 changed lines (Article 6).
- If the spec turns out to be wrong, stop, update the spec and get it
  approved again before the code continues.

## Step 5 — Done

An item is **Done** when its PR is merged, its unit tests pass, and every
check in the spec's verification table has been run. Checks that need real
data stay *Pending validation* (`docs/TESTING_GUIDELINES.md`).

---

## Conventions

### Layout

```
app/api/
├── requirements.in / requirements.txt
├── requirements-dev.in / requirements-dev.txt
├── server/
│   ├── main.py          # create_app(), run with uvicorn --factory
│   ├── settings.py      # Settings, get_settings()
│   ├── request_log.py   # request log middleware
│   └── routes/          # one module per area, each with an APIRouter
└── tests/               # one test file per module or item
```

New areas add a module in `server/routes/`. Code shared by several routes
gets its own module in `server/` when the second consumer appears, not
before.

### Application factory

- `create_app(settings, frontend_dir)` builds a new, independent app. There
  is no global state, so tests can build as many apps as they need.
- Registration order: middleware first, then the API routers, then the
  frontend mount and the SPA fallback last, so the frontend never shadows a
  route.

### Routes

- **API routes** live under `/api/`. `/healthz` is the only exception.
- **No data in URLs.** Statement data, descriptions and file names never go
  in a path or query string. Ids are fine.
- **Unknown `/api` paths** return the JSON 404 below, never HTML.

### Errors

Every error from the API uses one format, which the frontend client
(`app/web/src/api/client.ts`) parses:

```json
{"error": {"code": "not_found", "message": "Recurso não encontrado."}}
```

- `code` is a stable, English, snake_case identifier. The frontend branches
  on it.
- `message` is in pt-BR, written for the end user, and never contains a
  stack trace, SQL, a file path or a value the user didn't type.
- A conflict (`409`) may add `version` with the current version of the
  resource, so the client can reload it.
- An unhandled exception returns `500` with no details. The details go to
  the log only (see "Logging").

### Settings

- All configuration comes from environment variables with the `PORTAL_`
  prefix, through `pydantic-settings` in `server/settings.py`.
- `PORTAL_ENV` is `dev` or `prod` and defaults to `prod`, so a missing
  variable never turns on dev behavior. Dev-only features check it and
  refuse to run in prod.
- Invalid settings stop the server at startup, with a message that names the
  variable and never prints its value.
- Secrets use `SecretStr`. Every new variable is added to the model and to
  `.env.example` (name and comment, no value) in the same PR.

### Logging

- One JSON line per request, from the request log middleware: timestamp,
  level, `request_id`, method, route template, status and duration.
- **Never logged:** query strings, request or response bodies, headers,
  client IPs, emails, file names and transaction descriptions.
- Code that logs something else follows the same rule: ids, counts, status
  and timing only.
- Tracebacks go to the log only when `PORTAL_ENV=dev`.

### Dependencies

- Direct dependencies go in `requirements.in` (runtime) or
  `requirements-dev.in` (tests and tools), without versions.
- The `.txt` files are compiled with `uv pip compile` for Python 3.14, pin
  everything with `==`, are committed, and are never edited by hand.
- A new dependency is listed in the spec of the item that needs it. Upgrades
  are a change of their own.

### Auth

- Today, access is enforced by Cloudflare Access at the edge only. The pages
  carry no data.
- **Before the first endpoint that returns data** (BE-02), the app verifies
  the Access JWT on every protected request (BE-23). `/healthz` is the only
  route exempted explicitly.
- Locally there is no Access. The dev bypass (BE-25) works only with
  `PORTAL_ENV=dev`.

### Data and third parties

- **Supabase:** FastAPI is the only client. The service-role key stays on the
  server and never reaches the browser, a response or a log.
- **Uploaded PDFs and extracted transactions are sensitive.** They are never
  written to the repo, `input/` and `outputs/` are never served, and they
  never enter the Docker image.
- **Anthropic and other APIs** are called only from the server, with keys
  held in settings.

### Tests

The full rules are in `docs/TESTING_GUIDELINES.md`. In short:

- pytest with FastAPI's `TestClient`, through `create_app()` with test
  settings built in code. Tests never read `.env`.
- Fictitious data only: the canonical fixture in `app/fixtures/` or other
  obviously fictitious data.
- Supabase, Cloudflare Access and Anthropic are replaced by fakes. No test
  calls a real service.
- `make test-api` runs them.

### Running

| Command (in `app/`) | Runs |
|---|---|
| `make dev` | uvicorn with reload on `127.0.0.1:8000`, plus Vite |
| `make serve` | uvicorn serving the built frontend, close to production |
| `make test-api` | the backend tests |

The server binds to `127.0.0.1` locally, and uvicorn's access log stays off
because the request log replaces it.
