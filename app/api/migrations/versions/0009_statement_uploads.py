"""statement_uploads: the encrypted PDF of a statement that is not ready (BE-04)

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_backend_only_rls

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_uploads",
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(ciphertext) > 0",
            name=op.f("ck_statement_uploads_ciphertext_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["statement_id"],
            ["portal.statements.id"],
            name=op.f("fk_statement_uploads_statement_id_statements"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("statement_id", name=op.f("pk_statement_uploads")),
        schema="portal",
    )
    enable_backend_only_rls("statement_uploads")


def downgrade() -> None:
    op.drop_table("statement_uploads", schema="portal")
