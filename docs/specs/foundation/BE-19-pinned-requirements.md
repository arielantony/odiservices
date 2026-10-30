# Spec — BE-19 Pin runtime dependencies

| | |
|---|---|
| **Backlog** | Platform › Project foundation › BE-19 |
| **Depends on** | BE-17 |
| **Spec status** | Approved, 2026-10-30 |
| **Date** | 2026-10-30 |

## 1. Goal

Builds are reproducible: the same `requirements.txt` installs the same
versions locally and on Lightsail.

## 2. Design

- **`app/api/requirements.in`** lists only the direct dependencies, without
  versions:
  - `fastapi`;
  - `uvicorn[standard]`;
  - `pydantic-settings`.
- **`app/api/requirements.txt`** is generated with
  `uv pip compile requirements.in --python-version 3.14 -o requirements.txt`.
  Every package, including transitive ones, is pinned with `==`. The file is
  committed and never edited by hand.
- **Dev dependencies** (pytest, httpx, linters) go in `requirements-dev.in` /
  `requirements-dev.txt`, starting with BE-17 (its test harness). They are
  pinned the same way and never enter the image.
- **Upgrades** recompile the file with `--upgrade`, in a change of their own.

Current versions on PyPI (2026-10-30), for reference only. The compile step
decides the final pins:

| Package | Version |
|---|---|
| fastapi | 0.162.0 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.2 |
| pydantic-settings | 2.16.2 |
| starlette | 1.10.0 |

## 3. Verification

| Check | Expected |
|---|---|
| Every line of `requirements.txt` | Pinned with `==` |
| `uv pip sync requirements.txt` in a clean venv | Succeeds, and the server starts |

## 4. Tests

`app/api/tests/test_requirements.py`:

| Test | Asserts |
|---|---|
| `test_runtime_requirements_are_pinned` | Every requirement line in `requirements.txt` uses `==` |
| `test_dev_requirements_are_pinned` | The same for `requirements-dev.txt` |
