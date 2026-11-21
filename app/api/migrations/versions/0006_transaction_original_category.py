"""transactions: the category the extraction gave each line (BE-13)

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

FK = "fk_transactions_original_category_code_categories"


def upgrade() -> None:
    # One transaction (migrations run in their own): the column is added, then
    # backfilled from the current category, then made NOT NULL. The order is
    # the point: NOT NULL before the backfill would fail on existing rows.
    op.add_column(
        "transactions",
        sa.Column("original_category_code", sa.Text(), nullable=True),
        schema="portal",
    )
    op.execute(
        "UPDATE portal.transactions SET original_category_code = category_code "
        "WHERE original_category_code IS NULL"
    )
    op.alter_column(
        "transactions",
        "original_category_code",
        existing_type=sa.Text(),
        nullable=False,
        schema="portal",
    )
    op.create_foreign_key(
        op.f(FK),
        "transactions",
        "categories",
        ["original_category_code"],
        ["code"],
        source_schema="portal",
        referent_schema="portal",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(FK), "transactions", schema="portal", type_="foreignkey")
    op.drop_column("transactions", "original_category_code", schema="portal")
