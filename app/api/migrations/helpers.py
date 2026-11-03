"""Helpers for table migrations (BE-31)."""

import re

from alembic import op

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def enable_backend_only_rls(table: str) -> None:
    """Turn on row level security for a table in `portal` and add the one
    policy: `app_backend` sees and writes every row. No other role has a
    policy, so it sees nothing. Every migration that creates a table calls
    this, and a test fails when one forgets."""
    if not _NAME.match(table):
        raise ValueError(f"not a plain table name: {table!r}")
    op.execute(f"ALTER TABLE portal.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY backend_only ON portal.{table} "
        "TO app_backend USING (true) WITH CHECK (true)"
    )
