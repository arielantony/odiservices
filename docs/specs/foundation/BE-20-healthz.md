# Spec — BE-20 Expose `/healthz`

| | |
|---|---|
| **Backlog** | Platform › Project foundation › BE-20 |
| **Depends on** | BE-17 |
| **Spec status** | Approved, 2026-10-30 |
| **Date** | 2026-10-30 |

## 1. Goal

An endpoint that monitors and the Docker healthcheck call to know the process
is up.

## 2. Design

`GET /healthz` returns:

- status `200`;
- body `{"status": "ok"}`;
- `Cache-Control: no-store`.

Other rules:

- **No auth.** BE-23 must exempt this path explicitly.
- **No details.** The response carries no version, environment or hostname.
- **Liveness only.** It does not check the database. When BE-26 lands, decide
  whether to add a separate readiness check; don't change this endpoint for it.
- **Not in the API docs.** It is excluded from the OpenAPI schema
  (`include_in_schema=False`).

## 3. Verification

| Check | Expected |
|---|---|
| `GET /healthz` | 200, `{"status":"ok"}`, `Cache-Control: no-store` |
| `HEAD /healthz` and `POST /healthz` | 405 |

## 4. Tests

`app/api/tests/test_health.py`:

| Test | Asserts |
|---|---|
| `test_healthz_ok` | 200, the body is exactly `{"status": "ok"}`, and `Cache-Control: no-store` |
| `test_healthz_rejects_other_methods` | `POST` gets 405 |
| `test_healthz_not_in_openapi` | `/healthz` is absent from `app.openapi()["paths"]` |
