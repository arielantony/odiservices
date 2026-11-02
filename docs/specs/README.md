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
| `deploy/` | Platform: Packaging and deployment |
| `database/` | Platform: Database (Supabase) |

New folders follow the same pattern (`upload/`, `board/`, `auth/`,
`database/`, `quality/`) and are created with their first spec.

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
7. **Prerequisites:** what must exist before the first line is written, as a
   table: the prerequisite, who provides it (owner or agent), the **preflight
   command** that proves it exists, and the expected output. Accounts,
   identities, credentials (their location, never their value), instances,
   tools, quotas and test data all count. See the Definition of Ready below.
8. **Assumptions to verify:** every claim about a platform, a tool or a
   service that the design depends on and that the author has not seen with
   their own eyes (how a provider runs a boot script, which shell, what a
   restart policy does after a manual kill). Each one is labeled *verified*
   or *assumed*. An *assumed* claim gets a cheap smoke test, planned in the
   item's first step, before anything is built on it.

Specs approved before 2026-11-01 are not rewritten. An item that has not
started yet adds sections 7 and 8 before it starts.

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

## Definition of Ready

**Ready** (in the backlog) means the spec is approved. An item is **started**
only when the Definition of Ready below is met. When the owner says to start
an item, the agent runs this gate first and reports it in one message:
what is green, what is missing and who provides it. Work starts when
everything is green, or when the owner accepts a listed gap in writing. The
point is to find the missing account, key or instance before the work, not in
the middle of it.

**Every item**

- The spec is approved and every **Depends on** item is Done.
- Open questions are answered or recorded as assumptions.
- Every verification check has an exact command and an expected result that
  can actually happen, runs when the item merges (see Verification), and,
  when it needs the owner, says who runs it. The checks were read once as a
  dry run when the spec was approved.
- The tests are listed with their fixtures.
- **Prerequisites** (section 7): every preflight command was run today and
  passed. Credentials are checked by their effect (a command that shows who
  you are), never by reading them.
- **Assumptions** (section 8) are labeled, and each *assumed* one has its
  smoke test in step 1.
- **Approvals:** the spec lists the actions that need the owner's explicit
  OK (install a package, create or destroy a resource, apply a plan, create
  a credential, push a scratch branch) and the owner's standing answer to
  each. The agent asks once, at the start, and not once per action.
- **Packages:** every install the item needs is listed in the spec.
  Anything else is asked first (`CLAUDE.md`).

**Infrastructure and deploy items also**

- **Identity:** a scoped, non-root identity and its CLI profile exist, and
  the preflight shows who it is (for AWS, `aws sts get-caller-identity`). No
  root keys. The owner creates access keys; the agent never sees them.
- **Inventory:** what already exists in the target account (instances,
  addresses, key pairs, state files) and whether the item reuses it or
  replaces it.
- **Cost:** the monthly cost, the cost of a failed attempt, and who destroys
  leftovers.
- **Access paths:** the SSH key, the allowed address range and any deploy
  key exist, outside the repository.
- **Tooling:** every tool and version the item uses is installed and was
  authorized in the spec (OpenTofu, shellcheck, nmap and so on).
- **Step 1 is a walking skeleton:** a throwaway run of the whole loop (apply,
  boot, connect, destroy) before the real script or image is written.
- **Live checks** have a timeout and a first, narrow scope. A check that
  cannot finish in a few minutes is split.

**Frontend items also:** the prototype and the stories are approved
(`docs/CONSTITUTION.md`, Article 2).

If implementation shows that the spec is wrong, the spec is updated and
re-approved before the code continues. The same applies to the frontend
prototype (`docs/CONSTITUTION.md`, Article 2).
