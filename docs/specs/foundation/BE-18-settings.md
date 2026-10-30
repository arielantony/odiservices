# Spec — BE-18 Load settings from environment variables

| | |
|---|---|
| **Backlog** | Platform › Project foundation › BE-18 |
| **Depends on** | BE-17 |
| **Spec status** | Approved, 2026-10-30 |
| **Date** | 2026-10-30 |

## 1. Goal

Configuration comes only from environment variables. It is validated once at
startup, and secrets are never committed.

## 2. Scope

**In scope:** the settings model, `.env.example`, and the startup failure on
invalid settings.

**Out of scope:** Supabase, Access and Anthropic variables. Each is added by
the item that uses it (BE-23, BE-26, BE-03), always to both the model and
`.env.example`.

## 3. Design

`server/settings.py` defines a `pydantic-settings` `Settings` class with the
prefix `PORTAL_`:

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `PORTAL_ENV` | `dev` \| `prod` | `prod` | Environment. Later items use it to refuse dev-only features (such as BE-25) in prod. |
| `PORTAL_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Log level |

Rules:

- **Safe default:** `PORTAL_ENV` defaults to `prod`, so a missing variable
  never turns on dev behavior.
- **`.env` loading:** `app/.env` is read when present (local
  development only). It is ignored by git and kept out of the Docker image
  (OPS-01).
- **Fail fast:** an invalid value stops the server at startup, with an error
  that names the variable but never prints its value.
- **Secrets:** secret fields added later use `SecretStr`, so they never appear
  in `repr()` or in logs.
- **Single instance:** `get_settings()` is cached, and `create_app()` accepts
  an explicit `Settings` for tests.
- **`.env.example`:** lists every variable name with a comment and no real
  values, and is committed.

## 4. Verification

| Check | Expected |
|---|---|
| Start with no variables set | Runs with `env=prod` |
| `PORTAL_ENV=staging` | Startup fails, and the message names `PORTAL_ENV` |
| `.env.example` | Lists every field of `Settings` |
| `git check-ignore app/.env` | Ignored |

## 5. Tests

`app/api/tests/test_settings.py`. These tests set environment variables with
`monkeypatch` and never read a real `.env`:

| Test | Asserts |
|---|---|
| `test_defaults_to_prod` | With no variables set, `env == "prod"` and `log_level == "INFO"` |
| `test_rejects_unknown_env` | `PORTAL_ENV=staging` raises a validation error that names the variable |
| `test_error_does_not_echo_value` | The error message for an invalid value doesn't contain the value |
| `test_env_example_lists_every_field` | Every `Settings` field appears in `.env.example`, and the file has no values |
