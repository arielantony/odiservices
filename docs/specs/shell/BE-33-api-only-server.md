# Spec — BE-33 Make the FastAPI server API-only

| | |
|---|---|
| **Backlog** | Portal shell › Backend › BE-33 |
| **Needed by** | OPS-01 (the `api` image has no `web/dist`) |
| **Depends on** | BE-01 |
| **Spec status** | Approved, 2026-10-30 |
| **Date** | 2026-10-30 |

## 1. Goal

The owner chose separate `api` and `web` containers (OPS-01). nginx in the
`web` image now serves the built React app, the SPA fallback and the asset
cache headers, and proxies `/api` and `/healthz` to this server. FastAPI stops
serving files, so it boots in `prod` without a `web/dist` and ships no frontend.

## 2. Scope

**In scope**

- Remove the static serving and the SPA fallback added by BE-01.
- Keep the JSON 404 for any unknown path.
- Keep the security headers and the request log.
- Update `make serve` and the docs that describe it.

**Out of scope**

| Excluded | Covered by |
|---|---|
| Serving the built app, SPA fallback, cache headers | `web/nginx` (OPS-01) |
| Content-Security-Policy | BE-32 (pages in nginx, API responses here) |

## 3. Design

### 3.1 What is removed

| Item | Change |
|---|---|
| `server/frontend.py` | Deleted, with `DEFAULT_FRONTEND_DIR`, `NOT_BUILT`, `IMMUTABLE`, `NO_CACHE` and the `dist` containment code |
| `create_app(settings, frontend_dir)` | The `frontend_dir` argument goes. `create_app(settings=None)` |
| The `install_frontend` call and its "must be last" ordering note in `main.py` | Removed. The comment keeps the order of middleware and routers |
| The `log_route` handling for files in `request_log.py` | Only `unmatched` remains for a request that matches no route. The static-file branch from #18 is removed with its test |
| The prod refusal to start without `dist` | Gone. `PORTAL_ENV=prod` boots with no `web/` directory anywhere |

### 3.2 What stays

- `GET /healthz` (BE-20).
- `SecurityHeadersMiddleware` (the three headers, on every response the API
  produces). nginx adds the same three to the responses it produces itself.
- `RequestLogMiddleware` (BE-21).

### 3.3 Unknown paths

Any path without a route (under `/api` or not) returns `404` in the error
format the frontend parses, and logs `unmatched`:

```json
{"error": {"code": "not_found", "message": "Recurso não encontrado."}}
```

This is a handler for the framework's 404, so a method mismatch (`405`) is
unchanged.

### 3.4 `make serve`

`make serve` runs the API alone on 127.0.0.1 (as before, minus the frontend).
To see the whole app locally, use `make dev` (Vite and the API) or, for the
packaged setup, `make compose-up` (OPS-02). `help`, `app/README.md` and
`CLAUDE.md` ("Dev setup") say so.

## 4. Files

| File | Change |
|---|---|
| `app/api/server/frontend.py` | Deleted |
| `app/api/server/main.py` | 3.1 and the 404 handler of 3.3 |
| `app/api/server/request_log.py` | 3.1 |
| `app/api/tests/test_frontend.py` | Deleted |
| `app/api/tests/test_not_found.py` | New. Section 6 |
| `app/api/tests/test_request_log.py` | Drops the static-file case |
| `app/Makefile`, `app/README.md`, `CLAUDE.md` | 3.4 |
| `docs/specs/shell/BE-01-serve-portal-pages.md` | Header note: sections 3.1 to 3.4 and the frontend-dir rules are superseded by BE-33 and OPS-01 |

## 5. Verification

| Check | Expected |
|---|---|
| `make serve`, with no `web/dist` | The server starts in the default (`prod`) environment |
| `GET /healthz` | 200, `{"status":"ok"}` |
| `GET /`, `GET /api/nope`, `GET /.env` | 404 and the JSON body above, never a file |
| The three headers | Present on `/healthz` and on a 404 |
| `grep -rn "web/dist\|frontend_dir\|install_frontend" app/api` | Nothing |
| `make test-api` | Passes |

## 6. Tests

`test_not_found.py`, with `create_app()` and `TestClient`:

| Test | Asserts |
|---|---|
| `test_unknown_api_path_is_json_404` | `/api/nope` is 404 with the body of 3.3 |
| `test_unknown_page_path_is_json_404` | `/` and `/categorizer` are 404 with the same body. No HTML |
| `test_security_headers_on_404` | The three headers are on the 404 |
| `test_boots_in_prod_without_a_frontend` | `create_app()` with `env=prod` works with no `web/dist` |
| `test_unmatched_404_is_logged_without_the_path` | The request log event for it has `route: "unmatched"` |

## 7. Open questions

1. **Remove or keep BE-01's code.** The owner asked for removal.
   *Recommendation:* remove, as specified, since two sources of truth for the
   headers and the SPA rules would drift.
2. **Local full-app preview.** `make serve` no longer shows the app.
   *Recommendation:* accept it; `make dev` and `make compose-up` cover it.
