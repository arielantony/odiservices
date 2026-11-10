"""categories: the set of transaction categories, seeded (BE-30)

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import enable_backend_only_rls

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# (code, label in pt-BR, auto_assign). The two categories the owner uses only
# on request are auto_assign = false (BE-30, section 3.1).
SEED = [
    ("FORNECEDOR", "Fornecedor", True),
    ("OPERACIONAL", "Operacional", True),
    ("MARKETING/COMERCIAL", "Marketing/Comercial", True),
    ("INVESTIMENTO", "Investimento", True),
    ("DESPESA ADMINISTRATIVA", "Despesa administrativa", True),
    ("FOLHA DE PAGAMENTO", "Folha de pagamento", False),
    ("CUSTO DO CARRO", "Custo do carro", False),
    ("DESPESAS FINANCEIRAS", "Despesas financeiras", True),
    ("PESSOA FISICA", "Pessoa física", True),
    ("OUTROS", "Outros", True),
]


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "auto_assign",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code <> ''", name=op.f("ck_categories_code_not_empty")),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_categories_code_uppercase")),
        sa.CheckConstraint("label <> ''", name=op.f("ck_categories_label_not_empty")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_categories")),
        sa.UniqueConstraint("position", name=op.f("uq_categories_position")),
        schema="portal",
    )
    enable_backend_only_rls("categories")
    # The set changes only by migration or by SQL the owner runs (BE-30, 6.2):
    # the portal's role reads it and cannot write it.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON portal.categories FROM app_backend")

    categories = sa.table(
        "categories",
        sa.column("code", sa.Text()),
        sa.column("label", sa.Text()),
        sa.column("auto_assign", sa.Boolean()),
        sa.column("position", sa.Integer()),
        schema="portal",
    )
    op.bulk_insert(
        categories,
        [
            {"code": code, "label": label, "auto_assign": auto, "position": n}
            for n, (code, label, auto) in enumerate(SEED, start=1)
        ],
    )


def downgrade() -> None:
    op.drop_table("categories", schema="portal")
