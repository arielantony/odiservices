#!/bin/sh
# Clean up after merged pull requests (docs/CONSTITUTION.md, Article 6).
#
# For every worktree under .worktrees/ whose branch has a merged PR:
# remove the worktree, delete the local branch and delete the branch on
# origin if GitHub has not already done it. Then bring the local main up to
# date with origin/main (git pull --rebase).
#
# Safe to run at any time, from the repo root or any worktree. It skips a
# worktree with uncommitted changes, or whose branch has commits that are
# not in the merged PR, and says why. It keeps the remote branch if it has
# commits that are not in the merged PR.
#
# Usage: scripts/after-merge.sh [--dry-run]
# Also run by the Claude Code hooks in .claude/settings.json.

set -eu

DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=1

run() {
  if [ -n "$DRY" ]; then echo "  would run: $*"; else "$@"; fi
}

# The main checkout is the parent of the shared .git directory.
ROOT=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
cd "$ROOT"

git fetch --quiet --prune origin

git worktree list --porcelain | awk '
  /^worktree / { path = substr($0, 10) }
  /^branch /   { print path "\t" substr($0, 19) }
' | while IFS="$(printf '\t')" read -r path branch; do
  case "$path" in "$ROOT"/.worktrees/*) ;; *) continue ;; esac

  head=$(gh pr list --state merged --head "$branch" --json number,headRefOid \
    --jq '.[0] | select(.) | "\(.number) \(.headRefOid)"')
  [ -n "$head" ] || continue
  pr=${head%% *}
  merged_oid=${head#* }

  if [ ! -d "$path" ]; then
    echo "#$pr $branch: worktree folder already gone, pruning"
  elif [ -n "$(git -C "$path" status --porcelain)" ]; then
    echo "#$pr $branch: skipped, the worktree has uncommitted changes ($path)"
    continue
  elif [ "$(git rev-parse "$branch")" != "$merged_oid" ] &&
    ! git merge-base --is-ancestor "$branch" "$merged_oid"; then
    echo "#$pr $branch: skipped, the branch has commits that are not in the merged PR"
    continue
  else
    echo "#$pr $branch: merged, removing $path"
    run git worktree remove "$path"
  fi
  run git worktree prune
  run git branch -D --quiet "$branch"

  # The fetch --prune above dropped the remote-tracking ref if GitHub already
  # deleted the branch. Otherwise delete it, unless someone pushed to it
  # after the merge.
  remote_oid=$(git rev-parse --verify --quiet "refs/remotes/origin/$branch" || true)
  if [ -z "$remote_oid" ]; then
    :
  elif [ "$remote_oid" = "$merged_oid" ] ||
    git merge-base --is-ancestor "$remote_oid" "$merged_oid"; then
    echo "#$pr $branch: deleting origin/$branch"
    run git push --quiet origin --delete "$branch"
  else
    echo "#$pr $branch: kept origin/$branch, it has commits that are not in the merged PR"
  fi
done

# Bring local main up to date. It has no commits of its own (nobody pushes
# to main), so the rebase is a fast-forward.
if [ "$(git branch --show-current)" = main ]; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "main: skipped, the main checkout has uncommitted changes to tracked files"
  elif [ "$(git rev-parse main)" != "$(git rev-parse origin/main)" ]; then
    echo "main: rebasing on origin/main"
    run git pull --quiet --rebase origin main
  fi
else
  # Not checked out here: move the branch ref only if it fast-forwards.
  run git fetch --quiet origin main:main
fi
