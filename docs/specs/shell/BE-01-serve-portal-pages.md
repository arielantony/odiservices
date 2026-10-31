# Spec — BE-01 Serve the portal from FastAPI

| | |
|---|---|
| **Backlog** | Portal shell › Backend › BE-01 |
| **Needed by** | FE-01 and every frontend story |
| **Depends on** | BE-17, BE-18, BE-21, FE-23 (`make build-web`) |
| **Spec status** | Approved, 2026-10-30. Sections 1 to 5 were rewritten the same day for the approved React proposal (static `portal/` → built SPA). Amended in #18 (the request log's rule for static files, and its test), approved by the owner, 2026-10-30 |
| **Superseded by** | BE-33 and OPS-01: sections 3.1 to 3.4 and the frontend-dir rules no longer apply. The API serves no files; nginx in the `web` image does |
| **Date** | 2026-10-30 |

## 1. Goal

The FastAPI server serves the built React app (`app/web/dist/`, from FE-23)
and, as each item lands, the API the app calls. In production, one process
serves everything. In development, Vite serves the frontend and proxies the
API to this server (BE-17, 3.4).

## 2. Scope

**In scope:**

- serving `web/dist/` with its hashed assets;
- the SPA fallback;
- the JSON 404 for unknown `/api` paths;
- cache and security headers;
- behavior when `web/dist/` is missing.

**Out of scope:**

| Excluded | Covered by |
|---|---|
| Building the frontend | FE-23 |
| Real API endpoints | BE-02 to BE-16 |
| Auth | BE-23 to BE-25 (Q1) |
| Content-Security-Policy | BE-32 (Q3) |

The vanilla categorizer in `web/legacy/` is **not served** (proposal R9,
option A).

## 3. Design

### 3.1 Routes

Registered in this order, after the API routers (BE-17, 3.2):

| Path | Methods | Result |
|---|---|---|
| `/healthz` | GET | BE-20 |
| `/api/...` without a route | any | `404` JSON (3.3) |
| `/assets/...` | GET | A file from `dist/assets/` (Vite's hashed bundles), or `404` |
| A path that matches a file in `dist/` (for example `/favicon.ico`) | GET | That file |
| A path with a file extension that matches no file (for example `/missing.js`) | GET | `404`, so a missing asset never gets HTML back |
| Any other path (`/`, `/categorizer`, `/categorizer/abc-123`, …) | GET | `dist/index.html`. React Router decides what to render, including its own "not found" |

The fallback replaces the trailing-slash redirect. `/categorizer` and
`/categorizer/` both return `index.html`, and the router treats them the same.

The request log (BE-21) logs a static file by its path without the query
string, because a file path carries no ids. A request that matches no route and
no file logs `unmatched` (BE-21).

### 3.2 Frontend directory

`dist` is resolved from the package location
(`Path(server.__file__).parents[2] / "web" / "dist"`), never from the working
directory or a setting. `create_app()` accepts an optional `frontend_dir`
argument, which only tests use.

- **Containment:** every requested path is resolved and must stay inside
  `dist`. Anything else (`/../.env`, `/%2e%2e/.env`, symlinks pointing
  outside) gets a `404`.
- **Never reachable:** the repo root, `app/.env`, `api/`, `web/src/` and
  `web/legacy/`.
- **If `dist` is missing:**
  - with `PORTAL_ENV=prod`, the server refuses to start;
  - with `PORTAL_ENV=dev`, the API works, and frontend paths return `503`
    with the plain text "Frontend não compilado. Use `make dev` ou
    `make build-web`.".

### 3.3 Unknown API paths

Any `/api/...` path without a route returns `404` in the error format the
frontend parses:

```json
{"error": {"code": "not_found", "message": "Recurso não encontrado."}}
```

The React API client (FE-23) keeps the `ApiError` contract of the current
`api.js`. Until the statement endpoints exist (BE-03 onward), screens that
call them show this error. That is expected, not mocked data.

### 3.4 Headers

| Response | Header |
|---|---|
| `index.html` (direct or through the fallback) | `Cache-Control: no-cache` |
| `/assets/...` (hashed names) | `Cache-Control: public, max-age=31536000, immutable` |
| Other files in `dist/` | Starlette defaults (`ETag`, `Last-Modified`) |
| Every response | `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY` |

## 4. Verification

These checks run with `make serve`, after `make build-web` (FE-23):

| Check | Expected |
|---|---|
| `GET /`, `/categorizer`, `/categorizer/abc-123` | 200, `text/html`, the same `index.html`, `Cache-Control: no-cache` |
| `GET /assets/<a built file>` | 200, the right content type, the `immutable` cache header |
| `GET /missing.js` | 404, not HTML |
| `GET /api/submissions` (before BE-03) | 404 with the JSON body from 3.3 |
| `POST /api/anything` | 404 JSON (not 405, not HTML) |
| `GET /.env`, `/../.env`, `/%2e%2e/.env`, `/ask_pdf.py`, `/legacy/index.html` | 404, and never the file's content |
| `PORTAL_ENV=prod` with no `dist` | Startup fails with a clear message |
| Any response | Carries the three headers in 3.4 |
| Open `/` in Chrome and follow the links | Pages render, with no 404 in the network panel except the expected `/api` ones |

## 5. Tests

`app/api/tests/test_frontend.py`. Each test builds a temporary `dist/`
(a fictitious `index.html`, `assets/app-abc123.js`, `favicon.ico`) with a
`.env` and a `secret.txt` next to it. The temporary directory is passed as
`frontend_dir`:

| Test | Asserts |
|---|---|
| `test_root_serves_index` | `GET /` is 200, HTML, `no-cache` |
| `test_client_routes_fall_back_to_index` | `/categorizer`, `/categorizer/`, `/categorizer/abc-123` return the `index.html` body |
| `test_hashed_assets_are_immutable` | `/assets/app-abc123.js` is 200, JavaScript, with the `immutable` header |
| `test_missing_file_with_extension_is_404` | `/missing.js` is 404, not HTML |
| `test_unknown_api_path_is_json_404` | GET and POST to `/api/nao-existe` are 404 with `{"error":{"code":"not_found",…}}` |
| `test_traversal_is_blocked` | `/../.env`, `/%2e%2e/.env` and `/../secret.txt` are 404, and the body never contains their content |
| `test_security_headers_on_every_response` | The three headers are on HTML, assets, JSON and 404 responses |
| `test_static_file_logged_by_path` | `GET /assets/app-abc123.js?x=fulano@exemplo.com` logs `route` `/assets/app-abc123.js`, with no query string |
| `test_healthz_not_shadowed` | `/healthz` still returns the JSON from BE-20 |
| `test_missing_dist_fails_in_prod` | `create_app(prod settings, frontend_dir=<missing>)` raises |
| `test_missing_dist_is_503_in_dev` | In dev, `/` is 503 and `/healthz` is 200 |

## 6. Open questions

Answers (2026-10-30):

- **Q1:** Access at the edge only for now. BE-23 comes before BE-02.
- **Q2:** superseded. React was approved
  (`docs/proposals/monorepo-and-react.md`), and sections 1 to 5 reflect it.
- **Q3:** a separate item, BE-32, confirmed by the owner. BE-01 doesn't wait
  for it. BE-32 lands before the first deploy (OPS-03), preferably before
  FE-03.

1. **Auth in this slice:** Should the app verify the Access JWT on page
   requests now, or rely only on Access at the edge?
   *Recommendation:* the edge only, for now. The pages carry no data.
   Verifying the JWT in the app (BE-23) becomes mandatory before the first
   endpoint that returns data (BE-02). Locally there is no Access, so nothing
   changes for development.
2. **Static files or templates:** With Jinja, the top bar becomes one shared
   partial, and later the signed-in user can be rendered on the server.
   *Recommendation:* static files for now. There are only two pages, the
   frontend stays plain HTML, and FE-01 repeats the top bar markup in both.
   Revisit when a third page appears, or when the user identity replaces
   "Equipe financeira".
3. **Content-Security-Policy:** A strict CSP needs the Google Fonts hosts
   allowed and the inline scripts and styles checked.
   *Recommendation:* add it as a new item (**BE-32**, Project foundation) and
   don't hold BE-01 for it.
