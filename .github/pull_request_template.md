<!--
Format required by docs/CONSTITUTION.md, Article 6. Remove these comments.
Title: "<ID>, step N of M: <short title>" for a step PR (base: the feature branch),
"<ID>: <short title>" for a single-step item or the final feature → main PR,
or "docs: <summary>" for a change with no backlog item.
-->

## <ID>, step N of M: <short title>

Backlog: <Feature> › <Area> › <ID>. Spec: [`docs/specs/<area>/<ID>-<name>.md`](../blob/main/docs/specs/<area>/<ID>-<name>.md) (<sections>).

Base: `feature/<id>-<slug>` (step N of M) | `main`.

<!--
Final feature → main PR only: list the merged step PRs (#.., #..), and write
How to test and Verification for the whole item.
Add anything else the reviewer must know first.
-->

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

1. `git fetch && git worktree add .worktrees/<branch> <branch>`
2. `cd .worktrees/<branch>/app && make <target>`
3. Open <URL> and <action>. Expected: <result>.

### Tests

`<command>`: <N> passed (<test files>). <Other checks: type check, build, lint>.

### Verification (spec section <N>)

- [x] <check that was run and passed>
- [ ] Pending validation: <check> (needs the owner's real data; the only box that may stay unchecked)
