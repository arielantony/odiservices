"""transactions: one row per line of a card statement (BE-29)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_backend_only_rls

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("printed_date", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("category_code", sa.Text(), nullable=False),
        sa.Column(
            "doubtful",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "reviewed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "item_number >= 1", name=op.f("ck_transactions_item_number_positive")
        ),
        sa.CheckConstraint(
            "section in ('purchases', 'international', 'products')",
            name=op.f("ck_transactions_section_known"),
        ),
        sa.CheckConstraint(
            "printed_date <> ''", name=op.f("ck_transactions_printed_date_not_empty")
        ),
        sa.CheckConstraint(
            "description <> ''", name=op.f("ck_transactions_description_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["portal.statements.id"],
            name=op.f("fk_transactions_statement_id_statements"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_code"],
            ["portal.categories.code"],
            name=op.f("fk_transactions_category_code_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint(
            "statement_id", "item_number", name=op.f("uq_transactions_statement_id")
        ),
        schema="portal",
    )
    op.create_index(
        op.f("ix_transactions_statement_id_category_code"),
        "transactions",
        ["statement_id", "category_code"],
        unique=False,
        schema="portal",
    )
    enable_backend_only_rls("transactions")


def downgrade() -> None:
    op.drop_table("transactions", schema="portal")
