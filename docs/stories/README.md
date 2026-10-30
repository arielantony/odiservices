# Frontend stories — OdiServices Portal

Frontend user stories for the portal, derived from prototype
[`docs/prototypes/portal/v3.html`](../prototypes/portal/v3.html). Each story is a
Gherkin `.feature` file, grouped in a folder per screen. Its acceptance
criteria can later run as automated tests.

v3 was approved on 2026-10-30, with amendments
(`docs/prototypes/portal/README.md`). Each story stays **Draft** until its
spec in `docs/specs/` is approved. FE-01 is the first one Ready.

## Conventions

- **One story per `.feature` file.** The file is named `FE-NN-<slug>.feature`
  and its first tag is the story ID.
- **Tags:** `@FE-NN`, the prototype version (`@prototype-v3`) and the status
  (`@draft`, `@ready`, `@pending-validation`, `@done`), mirrored from the
  backlog.
- **Language:** keywords, step text and file names are in English. Quoted
  strings are UI copy in pt-BR, exactly as they appear in the prototype.
- **Fictitious data only.** The board scenarios use the statement shown in v3
  (17 transactions, total R$ 11.906,35). It is the fixture behind the step
  `Given the fictitious statement "Fatura Cartão Exemplo, set/2026"`.
- Steps describe what the user sees and does. They never name endpoints,
  selectors or storage.

## Status and backlog

Status, dependencies and the full list of stories live in
[`docs/BACKLOG.md`](../BACKLOG.md), in the **Frontend** table of each feature.
That is the single source of truth. The `@draft` / `@ready` / `@done` tag in
each `.feature` file mirrors it and changes in the same commit.

A story becomes Ready only when its spec in [`docs/specs/`](../specs/) is
approved, in addition to its prototype.

Stories marked *Needs prototype* in the backlog (FE-14 to FE-20) have no
`.feature` file yet. Their Gherkin is written after the prototype is approved.

| Folder | Screen | Backlog feature |
|---|---|---|
| `shell/`, `landing/` | Top bar, Landing | Portal shell |
| `categorizer-home/` | Categorizer home | Statement upload and processing |
| `board/` | Categorizer board | Statement board |

## What prototype v4 needs to cover

v3 shows only static, happy-path states. These states exist in today's
`app/portal/categorizer/` or are implied by v3, but have no design:

1. **Landing:** service card before any statement is sent.
2. **Upload:** wrong file type, file over 10 MB, upload in progress, upload
   failed, and what the new row is called before classification finishes.
3. **Statement list:** empty list, list failed to load.
4. **Processing:** what the user sees after opening a statement that is still
   being classified (today: status panel with a progress bar).
5. **Review doubts:** the review overlay (FE-15), and the review button with 1
   or 0 doubts left.
6. **Keyboard and selection:** selected card, multi-selection bar, category
   picker opened by "Mover", `M` or `Ctrl+K` (FE-16).
7. **Drag and drop:** drop target highlight, save failure and rollback.
8. **Shortcuts help** panel, including "Desfazer todas as alterações" (FE-17).
9. **Filter:** no card matches.
10. **Delete:** confirmation and result (FE-18).
11. **Feedback:** toast after a move, confirmation or undo. Board failed to
    load.
12. **Small screens** for every screen (FE-20).
13. **Not found** page for unknown routes. FE-23 ships a plain text
    placeholder.

## Open questions

- **Landing "Para revisar":** does it count across all statements or only the
  latest one? FE-02 assumes all statements.
- **New upload name:** before extraction knows the card and period, is the
  row named after the file or after a placeholder?
- **Filter:** do lane counts and totals follow the filter, or keep showing the
  full statement?
- **Filter matching:** is it case- and accent-insensitive?
- **"Equipe financeira"** in the top bar: is it the team name or the signed-in
  user (Cloudflare Access identity)?
- **Category labels:** the database stores `FORNECEDOR`, but the UI shows
  "Fornecedor". Does the label mapping live in the API or the frontend?
  (BE-16)

## Running the scenarios

Not set up yet. The suggested setup is `pytest-bdd` with Playwright for
Python, tracked as QA-03 in `docs/BACKLOG.md`. The
scenarios then run against the portal served locally with fictitious fixtures.
