"""users: the people who signed in through Cloudflare Access (BE-27)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_backend_only_rls

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("access_subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
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
        sa.CheckConstraint("access_subject <> ''", name=op.f("ck_users_access_subject_not_empty")),
        sa.CheckConstraint("email <> ''", name=op.f("ck_users_email_not_empty")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("access_subject", name=op.f("uq_users_access_subject")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        schema="portal",
    )
    enable_backend_only_rls("users")


def downgrade() -> None:
    op.drop_table("users", schema="portal")
