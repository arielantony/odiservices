<!--
Format required by docs/CONSTITUTION.md, Article 6. Remove these comments.
Title: "<ID>, step N of M: <short title>" for a backlog item,
or "docs: <summary>" for a change with no backlog item.
-->

## <ID>, step N of M: <short title>

Backlog: <Feature> › <Area> › <ID>. Spec: [`docs/specs/<area>/<ID>-<name>.md`](../blob/main/docs/specs/<area>/<ID>-<name>.md) (<sections>).

<!-- Only if it applies: stacking, base branch, or anything the reviewer must know first. -->

### What changed

- `<path>`: <what changed and why>.
- `docs/BACKLOG.md`: <ID> set to <status>.

About <N> changed lines, excluding lockfiles and binaries.

### How to test

<!--
Steps the reviewer can follow from a clean checkout of this branch:
the commands, the URLs to open, what to do and what should happen.
Use fictitious data only (the canonical fixture, "Fatura Cartão Exemplo, set/2026").
-->

1. `git fetch && git worktree add ../odiservices-worktrees/<branch> <branch>`
2. `cd ../odiservices-worktrees/<branch>/app && make <target>`
3. Open <URL> and <action>. Expected: <result>.

### Tests

`<command>`: <N> passed (<test files>). <Other checks: type check, build, lint>.

### Verification (spec section <N>)

- [x] <check that was run and passed>
- [ ] <check not run yet>: <why, and when it will be>
