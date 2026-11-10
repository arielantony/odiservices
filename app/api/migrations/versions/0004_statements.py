"""statements: one row per card statement a person sends (BE-28)

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_backend_only_rls

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statements",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("total_lanc_atuais", sa.Numeric(precision=14, scale=2), nullable=True),
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
        sa.CheckConstraint("name <> ''", name=op.f("ck_statements_name_not_empty")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["portal.users.id"],
            name=op.f("fk_statements_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statements")),
        schema="portal",
    )
    op.create_index(
        op.f("ix_statements_user_id_created_at"),
        "statements",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
        schema="portal",
    )
    enable_backend_only_rls("statements")


def downgrade() -> None:
    op.drop_table("statements", schema="portal")
