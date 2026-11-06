#!/bin/sh
# Dump the production database (Supabase) before a migration
# (docs/deploy/supabase.md, step 2; docs/specs/database/BE-31-sql-migrations.md).
#
# Runs on the owner's machine only: it reads the owner's connection string
# (PORTAL_MIGRATION_DATABASE_URL) from ~/.config/odiservices/supabase.env, which
# the agent never reads. The dump holds real data once the portal has any, so it
# is written outside the repository, with mode 600.
#
# Needs pg_dump 17 or newer (a dump needs a client at least as new as the server).
#
# Usage: scripts/db-backup.sh [--dry-run]
#   --dry-run  check the setup and print where the dump would go; connect to nothing.
# Env:   ODISERVICES_ENV_FILE   the env file (default ~/.config/odiservices/supabase.env)
#        ODISERVICES_BACKUP_DIR the output folder (default ~/odiservices-backups)

set -eu

ENV_FILE="${ODISERVICES_ENV_FILE:-$HOME/.config/odiservices/supabase.env}"
BACKUP_DIR="${ODISERVICES_BACKUP_DIR:-$HOME/odiservices-backups}"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=1

die() { echo "db-backup: $*" >&2; exit 1; }

# The dump must never land inside a repository.
if git -C "$(dirname "$BACKUP_DIR")" rev-parse --git-dir >/dev/null 2>&1; then
  die "BACKUP_DIR is inside a git repository: $BACKUP_DIR"
fi

command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found (brew install postgresql@17)"
version=$(pg_dump --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')
[ "$version" -ge 17 ] || die "pg_dump $version is too old: 17 or newer is needed"

[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"
mode=$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")
[ "$mode" = "600" ] || die "$ENV_FILE has mode $mode, expected 600 (chmod 600 it)"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[ -n "${PORTAL_MIGRATION_DATABASE_URL:-}" ] || die "PORTAL_MIGRATION_DATABASE_URL is not set in $ENV_FILE"

# pg_dump wants a plain postgresql:// URL, without the +psycopg driver suffix.
url=$(printf '%s' "$PORTAL_MIGRATION_DATABASE_URL" | sed 's/+psycopg//')
out="$BACKUP_DIR/supabase-$(date +%Y%m%d-%H%M).dump"

if [ -n "$DRY" ]; then
  echo "db-backup: ok, pg_dump $version, env file mode 600"
  echo "db-backup: would write $out"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077
pg_dump "$url" --no-owner -Fc -f "$out"

[ -s "$out" ] || die "the dump is empty: $out"
objects=$(pg_restore --list "$out" | grep -c ' portal ' || true)
[ "$objects" -gt 0 ] || die "the dump has no objects in the portal schema: $out"

echo "db-backup: wrote $out ($(du -h "$out" | cut -f1), $objects portal objects)"
