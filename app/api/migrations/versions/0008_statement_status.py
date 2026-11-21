"""statements: the processing status and the failure code of each statement (BE-07)

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# The vocabulary of BE-07 (spec 3.2 and 3.4). server/statements.py holds the same
# values; test_migration_vocabulary_matches_code keeps the two equal.
STATUSES = ("processing", "ready", "failed")
FAILURE_CODES = (
    "invalid_pdf",
    "extraction_unavailable",
    "extraction_timeout",
    "extraction_refused",
    "extraction_truncated",
    "extraction_invalid",
    "unknown_category",
    "total_mismatch",
    "interrupted",
    "upload_not_available",
    "unknown",
)


def _literal_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


STATUS_KNOWN = f"status in ({_literal_list(STATUSES)})"
FAILURE_CODE_KNOWN = f"failure_code is null or failure_code in ({_literal_list(FAILURE_CODES)})"
FAILURE_CONSISTENT = "(status = 'failed') = (failure_code is not null)"


def upgrade() -> None:
    # The server default fills every existing row with 'ready', which is correct:
    # the statements already stored were imported and read as ready.
    op.add_column(
        "statements",
        sa.Column("status", sa.Text(), server_default=sa.text("'ready'"), nullable=False),
        schema="portal",
    )
    op.add_column(
        "statements",
        sa.Column("failure_code", sa.Text(), nullable=True),
        schema="portal",
    )
    op.create_check_constraint(
        op.f("ck_statements_status_known"), "statements", STATUS_KNOWN, schema="portal"
    )
    op.create_check_constraint(
        op.f("ck_statements_failure_code_known"),
        "statements",
        FAILURE_CODE_KNOWN,
        schema="portal",
    )
    op.create_check_constraint(
        op.f("ck_statements_failure_consistent"),
        "statements",
        FAILURE_CONSISTENT,
        schema="portal",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_statements_failure_consistent"), "statements", schema="portal", type_="check"
    )
    op.drop_constraint(
        op.f("ck_statements_failure_code_known"), "statements", schema="portal", type_="check"
    )
    op.drop_constraint(
        op.f("ck_statements_status_known"), "statements", schema="portal", type_="check"
    )
    op.drop_column("statements", "failure_code", schema="portal")
    op.drop_column("statements", "status", schema="portal")
