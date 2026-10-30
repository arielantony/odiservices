# Specs — OdiServices Portal

A spec describes **how** one backlog item will be built. The story or the
backlog item describes **what**. Every frontend story and every backend task
gets a spec, and **nothing is implemented before its spec is approved**.

## Where specs live

One Markdown file per backlog ID, in a folder per backlog area:

| Folder | Backlog area |
|---|---|
| `shell/` | Feature: Portal shell (frontend and backend) |
| `foundation/` | Platform: Project foundation |

New folders follow the same pattern (`upload/`, `board/`, `auth/`,
`database/`, `deploy/`, `quality/`) and are created with their first spec.

File name: `<ID>-<slug>.md`, for example `FE-01-top-bar-navigation.md` or
`BE-17-fastapi-project.md`. Written in English. UI strings are quoted in pt-BR.

## What a spec contains

Every spec starts with a header table: item, related story or prototype,
dependencies, spec status and date. Then:

1. **Goal:** one paragraph.
2. **Scope:** in scope and out of scope, naming the item that covers each
   excluded part.
3. **Design:** behavior, contracts (routes, payloads, settings, files) and the
   changes per file.
4. **Verification:** one concrete check per acceptance criterion or Gherkin
   scenario. Every check must be runnable when the item's last PR merges,
   with only the item itself and its **Depends on** items. A check that
   needs a later item belongs in that item's spec, which then lists this
   item in its Depends on. The same applies to commands: a Makefile target
   or script the item adds must work when it merges. *Pending validation*
   (the owner's real data) is the only kind of check that may wait.
5. **Tests:** the unit tests this item ships with, given as test name, what it
   asserts and the fixture it uses. They follow `docs/TESTING_GUIDELINES.md`:
   fictitious data only, and an item is Done only when they pass.
6. **Open questions:** each one with a recommended option. A question that
   gets no answer becomes an assumption with the recommended option, and is
   recorded as such.

If the item would change more than 500 lines, the Design section also lists
the **steps**, one pull request each (`docs/CONSTITUTION.md`, Article 6).

Specs are short. A small task (a health endpoint, a pinned requirements file)
fits in a few lines per section.

## Spec status

| Status | Meaning |
|---|---|
| In review | Written and waiting for the product owner |
| Approved | Approved explicitly, for example "spec BE-17 approved" |
| Superseded | Replaced by a newer spec; the file stays for history |

Approval is recorded in the spec header with its date. A backlog item becomes
**Ready** only when its spec is approved (see `docs/BACKLOG.md`).

If implementation shows that the spec is wrong, the spec is updated and
re-approved before the code continues. The same applies to the frontend
prototype (`docs/CONSTITUTION.md`, Article 2).
