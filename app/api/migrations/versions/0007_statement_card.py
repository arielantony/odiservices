"""statements: the card name and the last four digits of the card (BE-09)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both columns are nullable with no default: the statements already stored
    # were imported without a card, and NULL is correct for them.
    op.add_column(
        "statements",
        sa.Column("card_name", sa.Text(), nullable=True),
        schema="portal",
    )
    op.add_column(
        "statements",
        sa.Column("card_last4", sa.CHAR(4), nullable=True),
        schema="portal",
    )
    op.create_check_constraint(
        op.f("ck_statements_card_name_not_empty"),
        "statements",
        "card_name <> ''",
        schema="portal",
    )
    op.create_check_constraint(
        op.f("ck_statements_card_last4_digits"),
        "statements",
        "card_last4 ~ '^[0-9]{4}$'",
        schema="portal",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_statements_card_last4_digits"), "statements", schema="portal", type_="check"
    )
    op.drop_constraint(
        op.f("ck_statements_card_name_not_empty"), "statements", schema="portal", type_="check"
    )
    op.drop_column("statements", "card_last4", schema="portal")
    op.drop_column("statements", "card_name", schema="portal")
