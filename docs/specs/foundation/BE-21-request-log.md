# Spec — BE-21 Log requests without PII

| | |
|---|---|
| **Backlog** | Platform › Project foundation › BE-21 |
| **Depends on** | BE-17, BE-18 |
| **Spec status** | Approved, 2026-10-30 |
| **Date** | 2026-10-30 |

## 1. Goal

Each request leaves one log line that is enough to debug and monitor the
server, and that never contains personal or financial data.

## 2. Design

`server/request_log.py` is an ASGI middleware. It writes one JSON line to
stdout per request, when the response finishes:

```json
{"ts":"2026-10-30T12:00:00.123Z","level":"INFO","event":"request","request_id":"7f3c…","method":"GET","route":"/healthz","status":200,"duration_ms":1.8}
```

| Field | Rule |
|---|---|
| `route` | The matched route template (for example `/api/submissions/{id}`), not the raw path. For static files, the path without the query string. |
| `request_id` | The incoming `Cf-Ray` header when present, otherwise a new UUID4. It is returned to the client in `X-Request-Id`. |
| `level` | `INFO` for 2xx/3xx, `WARNING` for 4xx, `ERROR` for 5xx. |

**Never logged:**

- query strings;
- request or response bodies;
- headers, including `Cookie`, `Cf-Access-Jwt-Assertion` and `Authorization`;
- client IP addresses;
- user email;
- file names;
- transaction descriptions.

Unhandled exceptions are logged with their exception type and the
`request_id`. The traceback goes to the log only when `PORTAL_ENV=dev`.

Uvicorn's own access log is turned off (`--no-access-log`), because it writes
the raw path and the client IP.

## 3. Verification

| Check | Expected |
|---|---|
| `GET /healthz?email=a@example.com` | The log line has `route` `/healthz`, and the line contains no `@` and no `email` |
| Response header | `X-Request-Id` matches the logged `request_id` |
| A route that raises | One `ERROR` line, and the client gets a 500 with no stack trace |
| Uvicorn access log | Off |

## 4. Tests

`app/api/tests/test_request_log.py`. These tests capture stdout with `capsys`
and send fictitious values that are easy to spot, such as
`fulano@exemplo.com` and "Papelaria Fictícia":

| Test | Asserts |
|---|---|
| `test_one_json_line_per_request` | A single line that parses as JSON and has every field in section 2 |
| `test_route_template_not_raw_path` | A request to a parametrized route logs the template, not the id |
| `test_no_query_string_logged` | `?email=fulano@exemplo.com` leaves no trace (no `@`, no `fulano`) |
| `test_no_headers_logged` | `Cookie`, `Authorization` and `Cf-Access-Jwt-Assertion` values never appear |
| `test_request_id_from_cf_ray` | With `Cf-Ray`, the logged `request_id` and the `X-Request-Id` header both equal it |
| `test_request_id_generated` | Without `Cf-Ray`, `request_id` is a UUID4 that matches the header |
| `test_level_by_status` | 404 logs `WARNING`, and a raising route logs `ERROR` and returns 500 with no traceback in the body |
