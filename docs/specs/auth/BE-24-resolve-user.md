# Spec — BE-24 Resolve the Access identity to a `users` row

| | |
|---|---|
| **Backlog** | Platform › Authentication › BE-24 |
| **Depends on** | BE-23, BE-26, BE-27 |
| **Spec status** | Approved (2026-11-07), with the answers in section 6. Questions 8 and 9 are accepted as recommended |
| **Date** | 2026-11-07 |

## 1. Goal

A request that carries a valid Access token (BE-23) becomes a request made by
a known person: the API finds the `portal.users` row for the token's `sub`,
and creates it the first time that person is seen. A route that needs the
person declares one dependency, `current_user`, and gets the `User`. This is
what lets every later record belong to a user (backlog note for BE-24) and it
is the base BE-34 builds roles on.

The email is stored once, when the row is created, and **never updated**
(owner decision, 2026-11-07). When the token carries a different email than
the row, the API does not change the row. It flags the event in the log, so
the owner can look at it.

## 2. Scope

**In scope**

- `server/users.py`: `current_user`, the lookup, the creation and the flag.
- `server/db/session.py`: a request-scoped database session, and the engine
  held by the app (built from `PORTAL_DATABASE_URL`, lazily).
- `GET /api/me`: the first route that uses `current_user`. It answers the
  person's `id` only.
- The refusals: a token with no email and no row, an email that belongs to
  another person, and a database that is not configured or not reachable.
- Tests, and the owner's live check on the production host.

**Out of scope**

- Which service a person may open (roles): BE-34. A row grants nothing.
- Changing a stored email, or merging two rows: a manual change by the owner
  in SQL, outside this item. The flag in the log is how the owner finds out.
- Showing the person's name or email in the interface: a frontend item.
- The local development bypass: BE-25. Tests use the fake Access of BE-23.
- Caching the lookup. One indexed `SELECT` per request is enough for now.

## 3. Design

### 3.1 The resolution

`current_user(identity, session) -> User`. The identity comes from
`Depends(require_access)`, which FastAPI evaluates once per request, so the
token is verified once and shared. The email is normalized first with
`strip().lower()`, and an email that is empty after that counts as absent.

1. `SELECT` the row by `access_subject = identity.subject`.
2. **A row exists.** Return it. If the token has an email and it differs from
   `user.email`, **flag** it (3.3) and still return the stored row. Nothing is
   updated: not the email and not `updated_at`.
3. **No row, and the token has no email.** Refuse with a 403 (3.2). A token
   with no email is not a person (BE-27, question 6), so it gets no row.
4. **No row, and the token has an email.** `INSERT ... ON CONFLICT
   (access_subject) DO NOTHING`, commit, and `SELECT` by subject again. The
   conflict clause covers two first requests of the same person arriving
   together: the second one inserts nothing and reads the row the first made.
5. **The insert breaks `uq_users_email`.** The email belongs to a row with
   another `sub`. Refuse with a 409 (3.2), create nothing, and flag it (3.3).
   Any other integrity error is a bug and becomes the usual 500.

The row is created by the first request that reaches a route using
`current_user`, which is the first call to `/api/me` after a login. There is
no separate "login" step: Access owns the login, and the API only sees tokens.

### 3.2 Answers

Same JSON shape as the rest of the API, with `Cache-Control: no-store`. The
message is in pt-BR and never says which rule failed.

| Case | Status | `code` | `message` |
|---|---|---|---|
| Token has no email and the person has no row | 403 | `user_not_allowed` | "Seu acesso não pode ser identificado. Fale com o administrador." |
| The email already belongs to another `sub` | 409 | `user_conflict` | "Já existe um cadastro com este e-mail. Fale com o administrador." |
| `PORTAL_DATABASE_URL` is not set, or the database cannot be reached | 503 | `database_unavailable` | "Não foi possível acessar os dados. Tente novamente." |

A request with no valid token never gets here: BE-23 answers 401 first.

`GET /api/me` answers `{"id": "<uuid>"}` with `Cache-Control: no-store`. It
carries no email and no subject. The id is not secret and not personal data.

### 3.3 The flags

Two events are written as one JSON line to stdout, in the same style as
`access_not_configured` (BE-23): `ts`, `level`, `event`, and the ids. **Never
the email, the subject or the token**, in the log or in a response (BE-21,
and the owner's rule of 2026-11-04).

| Event | Level | When | Fields |
|---|---|---|---|
| `user_email_mismatch` | `WARNING` | A row exists and the token's email differs from the stored one | `user_id` |
| `user_email_conflict` | `WARNING` | The insert broke `uq_users_email` | none |
| `user_created` | `INFO` | A row was created | `user_id` |

`user_email_mismatch` repeats on every request of that person until the owner
fixes the row or the identity provider, because the check runs each time.
That is the point of a flag. How the owner reads it: look for the event in
the host's container log, take the `user_id`, and compare in SQL. The
`user_email_conflict` event has no id on purpose: the only id available
belongs to the row that was refused.

### 3.4 The database session

- `create_app(..., engine=None)` takes an optional engine (tests pass one for
  a throwaway database). Otherwise it builds `build_engine(settings.database_url)`
  when the setting exists, and keeps it in `app.state.engine`. `build_engine`
  is lazy, so **nothing connects at startup**: `/healthz`, the container
  checks and every test that does not touch the database behave as before.
- `get_session` is a plain `def` dependency (FastAPI runs it in its thread
  pool) that yields a `Session` from `app.state.engine` and closes it after the
  request. With no engine it raises the 503 above. A connection error raises
  the same 503, and the request log records the status. The exception class
  name is logged, never the message, because a driver message can hold the
  host.
- A lifespan hook disposes the engine on shutdown.
- No new setting: `PORTAL_DATABASE_URL` already exists (BE-26).

### 3.5 Files

| File | Change |
|---|---|
| `app/api/server/users.py` | New: `current_user`, `normalize_email`, the flag writers, `UserNotAllowed` and `UserConflict` (both `AccessError`-style errors) |
| `app/api/server/db/session.py` | New: `get_session` |
| `app/api/server/routes/me.py` | New: `GET /api/me` |
| `app/api/server/main.py` | Engine in `app.state`, lifespan to dispose it, the `me` router, the handler for the new errors |
| `app/api/tests/test_users_resolution.py` | New: unit tests, no database |
| `app/api/tests/test_users_resolution_db.py` | New: tests against the local Postgres, marked `db` |
| `docs/BACKEND_GUIDELINES.md` | Auth section: `current_user`, the email rule and the flag events |
| `docs/BACKLOG.md` | BE-24: spec link, status, PR links |

### 3.6 Steps

One step. About 350 changed lines with the tests, under the limit of 500.
Branch `feat/be-24-resolve-user` from `origin/main`, PR to `main`.

## 4. Verification

Every check runs when the item merges, with BE-23, BE-26 and BE-27.

| # | Check | Expected |
|---|---|---|
| 1 | From `app/`, with Docker stopped: `make test-api` | All tests pass |
| 2 | `make test-db` | The `db` tests pass, the BE-27 ones included |
| 3 | `make db-up && make db-upgrade`, then `make dev`, then `curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:8000/api/me` | `401`: no token, so BE-23 refuses before anything touches the database |
| 4 | `make dev` with `PORTAL_DATABASE_URL` unset, and `curl 127.0.0.1:8000/healthz` | `200`: the server starts with no database, as before |
| 5 | `grep -rn "email" app/api/server/users.py` | Every hit is a comparison, a column or a variable. None is in a `print`, a log call or a response |
| 6 | *Owner, after the deploy:* open `https://<portal host>/api/me` in the browser, signed in through Access | `{"id": "<uuid>"}`, 200 |
| 7 | *Owner:* in `psql` as the owner: `select count(*), min(created_at)=max(created_at) from portal.users` | `1`, `t` after step 6: one row, made by that first call |
| 8 | *Owner:* reload `/api/me` three times, then run the query of check 7 again | Still `1`, and the id in the answer does not change: no duplicate and no update |
| 9 | *Owner:* the host's container log has one `user_created` line and no `@` and no `sub` value | One line, with only the `user_id` |

Checks 6 to 9 need the item deployed, which is the existing deploy path
(`docs/deploy/lightsail.md`). The agent never connects to the host or to
Supabase.

## 5. Tests

`app/api/tests/`. The fake Access of BE-23 (`access_helpers.py`) supplies the
identity. Fictitious data only (`fulano@exemplo.com`, `sub-fulano`,
`outro@exemplo.com`).

`test_users_resolution.py` (no database)

| Test | Asserts |
|---|---|
| `test_me_without_token_is_401` | No token: 401, and the engine is never used |
| `test_normalize_email` | `" Fulano@Exemplo.COM "` becomes `fulano@exemplo.com`; `" "` and `None` become `None` |
| `test_no_database_configured_is_503` | A valid token and no engine: 503 `database_unavailable` |
| `test_database_error_is_503` | An engine whose connection fails: 503, and the body does not contain the driver message |
| `test_session_closed_after_request` | The session dependency closes the session, also when the route raises |
| `test_flags_have_no_personal_data` | The flag writers' output has no `@` and no subject, for a mismatch and a conflict |

`test_users_resolution_db.py`, marked `db` (the BE-31 fixtures)

| Test | Asserts |
|---|---|
| `test_first_request_creates_the_row` | A valid token for a new person: 200, one row, `access_subject` and the lowercased email stored, `user_created` logged |
| `test_second_request_reuses_the_row` | Same token twice: the same id, one row, `updated_at` unchanged |
| `test_email_is_stored_lowercase` | A token with `FULANO@Exemplo.com` stores `fulano@exemplo.com` |
| `test_email_change_is_flagged_not_applied` | An existing row and a token with another email: 200 with the stored row's id, the row unchanged (email and `updated_at`), and one `user_email_mismatch` line with the `user_id` and no email |
| `test_same_email_other_subject_is_409` | A row for `sub-fulano`; a token with `sub-outro` and the same email: 409 `user_conflict`, still one row, `user_email_conflict` logged |
| `test_token_without_email_and_no_row_is_403` | 403 `user_not_allowed`, no row created |
| `test_token_without_email_and_existing_row_passes` | An existing row and a token with no email: 200, the row unchanged |
| `test_insert_race_is_absorbed` | The row appears between the `SELECT` and the `INSERT` (the test inserts it in between): the request returns that row, with no error and no second row |
| `test_the_app_role_can_resolve` | The app runs as `app_backend` (RLS on): the whole flow works with only the grants of BE-27 |

## 6. Open questions

| # | Question | Answer |
|---|---|---|
| 1 | When is the row created? | **On the first verified request that reaches a route using `current_user`** (owner: follow the recommendation, 2026-11-07) |
| 2 | The same email with a new `sub`? | **409, nothing created, ids only in the log** (owner: follow the recommendation) |
| 3 | A token with no email? | **403 and no row**, when the person has no row (owner: follow the recommendation) |
| 4 | An email that changed for the same `sub`? | **Never updated. Flag it** (owner, 2026-11-07, overriding the recommendation). Read as: keep serving the stored row and write the `user_email_mismatch` warning. The request is not refused |
| 5 | The dependency? | **`current_user`**, on top of `require_access` (owner: follow the recommendation) |
| 6 | One upsert per request? | **Changed by question 4.** An upsert that writes every request would touch `updated_at` for nothing, and a conflict update would be an email update. So: one `SELECT` per request, and an `INSERT ... ON CONFLICT DO NOTHING` only for a new person. No cache |
| 7 | Depend on BE-25? | **No.** Tests use a fake identity (owner: follow the recommendation) |
| 8 | Which route first uses `current_user`? | **Accepted by the owner on approval (2026-11-07).** Recommended: a new `GET /api/me` that answers the `id` only. Without a route using it, no row would ever be created by this item, and `/api/session` stays free of the database so a session probe still works when the database is down |
| 9 | Is the mismatch flag enough, or should it also refuse the request? | **Accepted by the owner on approval (2026-11-07).** Recommended: only flag. Refusing would lock a person out over a changed mailbox, and the log line is the notice you asked for |

A question with no answer becomes an assumption with the recommended option.
Questions 8 and 9 were the agent's own recommendations; the owner accepted them when approving.

## 7. Prerequisites

| Prerequisite | Who | Preflight | Expected |
|---|---|---|---|
| BE-27 is applied locally and on Supabase | Agent, Owner | `make db-up && make db-upgrade && make db-current`, and on Supabase `make db-current` | `0002 (head)` both |
| The local database works | Agent | `make db-check` | `database ok (role=odiservices, postgres=17)` |
| The host has `PORTAL_DATABASE_URL` for `app_backend` through the pooler | Owner | `ssh <host> 'sudo grep -c ^PORTAL_DATABASE_URL= /etc/odiservices/.env'` | `1` (the count only, never the value) |
| The portal is reachable behind Access, for checks 6 to 9 | Owner | Open the portal URL in the browser | The Access login, then the portal |

**Packages.** None.

**Actions that need the owner's OK.** Approving this spec is the standing OK
for the pull request. This one needs a fresh OK when it comes up: **deploying
to the host** after the merge (checks 6 to 9), which the owner runs.

**Cost.** None.

## 8. Assumptions to verify

| # | Claim | Status | How it is checked |
|---|---|---|---|
| 1 | `INSERT ... ON CONFLICT (access_subject) DO NOTHING` does not swallow a conflict on `uq_users_email`: that one still raises | *Assumed*, from the Postgres documentation (only the named arbiter is handled) | `test_same_email_other_subject_is_409` |
| 2 | A row that conflicts on both the subject and the email is handled by `DO NOTHING`, with no error | *Assumed*, from the documentation (the arbiter index is checked first) | `test_insert_race_is_absorbed` |
| 3 | `Depends(require_access)` used by both the application and `current_user` runs once per request | *Assumed*, from FastAPI's per-request dependency cache | A test counts the verifier calls for one request: one |
| 4 | The `app_backend` role, with RLS on, can `SELECT` and `INSERT` on `portal.users` through the pooler | *Verified* locally in BE-27's tests; on Supabase it is *assumed* until BE-27 check 14 (already run) and check 6 here | `test_the_app_role_can_resolve`, and check 6 |
| 5 | The host already has `PORTAL_DATABASE_URL` set to the `app_backend` URL (BE-26) | *Assumed* | The preflight in section 7 |
| 6 | The Access `sub` is stable for one person, and `email` is present for a person who signs in through an identity provider | *Assumed*, from the Cloudflare documentation. BE-23 check 8 saw a real token with both | Check 6 and the first real row |
