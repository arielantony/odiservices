# Spec — BE-32 Content-Security-Policy on every response

| | |
|---|---|
| **Backlog** | Project foundation › Backend › BE-32 |
| **Origin** | BE-01 spec, open question 3 (confirmed by the owner, 2026-10-30) |
| **Depends on** | BE-01, BE-33, OPS-01 |
| **Needed by** | OPS-03 (due before it), preferably before FE-03 |
| **Spec status** | In review |
| **Date** | 2026-10-31 |

## 1. Goal

Every response carries a `Content-Security-Policy`. Pages get a policy that
allows only what the app loads today, so an injected script or a stray
third-party resource is blocked by the browser. API responses get a policy that
allows nothing. The policy is checked in a real browser, with no violation on
the landing page.

## 2. Scope

**In scope**

- A page policy in `web/nginx/`, on every response nginx produces itself.
- An API policy in `SecurityHeadersMiddleware`, on every response FastAPI
  produces.
- Keeping the two apart, so a response never carries both.
- Checks in `scripts/check-image.sh` and unit tests for the API side.

**Out of scope**

| Excluded | Covered by |
|---|---|
| Self-hosting the Google Fonts files (would drop two hosts from the policy) | Open question 1 |
| A violation reporting endpoint (`report-to`) | Not planned. There is no log sink for it and BE-21 forbids logging request details |
| A policy for `/docs`, `/redoc` and `/openapi.json` | BE-22 (Q3) |
| `Strict-Transport-Security` and TLS headers | OPS-04 (Cloudflare) |
| The Vite dev server (`make dev`) | Sends no CSP, because HMR needs inline code. Pages are checked through `make compose-up` |

## 3. Design

### 3.1 What the app loads today

Read from `web/index.html`, `web/src/` and a `yarn build`:

| Kind | Source | Directive |
|---|---|---|
| Scripts | One module bundle under `/assets/`, no inline script | `script-src 'self'` |
| Styles | The bundled CSS under `/assets/`, and the Google Fonts stylesheet | `style-src 'self' https://fonts.googleapis.com` |
| Fonts | Google Fonts files | `font-src https://fonts.gstatic.com` |
| Images | `/assets/` files and the `data:,` favicon | `img-src 'self' data:` |
| Fetch | `/api/*` and `/healthz`, same origin | `connect-src 'self'` |

There are no `style="…"` attributes in the HTML. React sets `style` props
through the DOM, which a CSP does not block, so `'unsafe-inline'` is **not**
needed.

### 3.2 Page policy (nginx)

```
default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

`frame-ancestors 'none'` is the modern twin of `X-Frame-Options: DENY`, which
stays for old browsers. Anything not listed falls back to `default-src 'self'`.

### 3.3 API policy (FastAPI)

```
default-src 'none'; frame-ancestors 'none'
```

JSON needs nothing. The header goes in `SECURITY_HEADERS`, next to the other
three, so it is on every response, including 404 and 500.

### 3.4 Keeping them apart in nginx

Today `headers.conf` is included in every location, and the proxied locations
(`/api/`, `/healthz`) forward the API's own headers. A response with two policies
is held to both, so the page policy would also restrict what the API may send.

| File | Content | Included in |
|---|---|---|
| `web/nginx/headers.conf` | The three headers, unchanged | Every location |
| `web/nginx/csp-page.conf` | `add_header Content-Security-Policy "…" always;` | Only the locations nginx answers itself: `/assets/`, dotfiles, files with an extension, `= /index.html` and `/` |

The proxied locations get no page CSP, so the API's policy is the only one on
`/api/*` and `/healthz`. The Dockerfile copies the new file.

### 3.5 Rules for later items

A change that needs a new source (a CDN, an inline style, a font host, an
analytics script) updates this policy in the same PR and its spec says so. A new
library that injects `<style>` tags (for example a drag and drop library in
FE-09) is checked against the policy in that item's verification.

## 4. Files

| File | Change |
|---|---|
| `app/web/nginx/csp-page.conf` | New. 3.2 |
| `app/web/nginx/default.conf.template` | Includes `csp-page.conf` in the locations of 3.4 |
| `app/web/Dockerfile` | Copies `csp-page.conf` |
| `app/api/server/security_headers.py` | Adds the 3.3 header and fixes the docstring |
| `app/api/tests/test_security_headers.py` | Section 6 |
| `app/scripts/check-image.sh` | CSP checks for pages and for the API |
| `docs/BACKLOG.md` | BE-32 gets this spec (In review) and the dependencies BE-33 and OPS-01 |

About 80 changed lines.

## 5. Verification

| Check | Expected |
|---|---|
| `make check-image` | Passes, including the new CSP checks |
| `curl -sI` on `/`, `/categorizer`, an `/assets/*` file and `/.env` | Each has exactly one `Content-Security-Policy`, equal to 3.2 |
| `curl -sI` on `/healthz` and `/api/nope`, through `web` | Each has exactly one `Content-Security-Policy`, equal to 3.3 |
| `curl -sI` on the `api` container directly | Same policy, equal to 3.3 |
| Open `/`, `/categorizer` and `/categorizer/abc-123` through `make compose-up` in Chrome (DevTools MCP) | The page renders with its fonts and logo. The console has no CSP violation. Chrome and the profile are closed afterwards (Article 4) |
| In the same page, inject an inline `<script>` through the console | The browser blocks it and logs a violation, proving the policy is enforced |
| `make test-api` | Passes |

## 6. Tests

`test_security_headers.py`, with `create_app()` and `TestClient`:

| Test | Asserts |
|---|---|
| `test_api_csp_on_every_response` | `/healthz` (200) and an unknown path (404) carry exactly `default-src 'none'; frame-ancestors 'none'` |
| `test_csp_on_a_500` | A route that raises still returns the header |
| `test_existing_headers_unchanged` | The three BE-01 headers are still present with their values |

The nginx side is covered by `check-image.sh` (section 5), as in OPS-01.

## 7. Open questions

1. **Google Fonts.** Allowing two outside hosts is the weakest part of the
   policy, and it sends each visitor's IP to Google.
   *Recommendation:* ship BE-32 with the two hosts, and add a small item to
   self-host Gilda Display and Montserrat, which then removes them from 3.2.
2. **Report-only first.** Sending `Content-Security-Policy-Report-Only` for a
   while would show violations without breaking pages.
   *Recommendation:* enforce directly. The app has one screen of real content,
   and with no reporting endpoint report-only shows nothing outside DevTools.
3. **Docs pages.** The default FastAPI `/docs` loads Swagger UI from a CDN, so
   the 3.3 policy breaks it when the API is opened directly. Behind `web` it is
   unreachable, because nginx proxies only `/api/` and `/healthz`.
   *Recommendation:* leave it to BE-22, which decides how docs are served and
   gives them their own policy.
