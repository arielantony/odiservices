"""The Category model and the seed, with no database (BE-30)."""

import importlib

from server.db import Category

SEED_MODULE = importlib.import_module("migrations.versions.0003_categories")

# The ten categories of the business's classification prompt (prompt-pdf.md),
# in the order of the prompt. The fixture is this list, not the migration.
PROMPT_CODES = [
    "FORNECEDOR",
    "OPERACIONAL",
    "MARKETING/COMERCIAL",
    "INVESTIMENTO",
    "DESPESA ADMINISTRATIVA",
    "FOLHA DE PAGAMENTO",
    "CUSTO DO CARRO",
    "DESPESAS FINANCEIRAS",
    "PESSOA FISICA",
    "OUTROS",
]


def test_repr_shows_the_code_not_the_label():
    category = Category(code="OUTROS", label="Outros", auto_assign=True, position=10)
    assert repr(category) == "<Category OUTROS>"


def test_seed_list_matches_the_prompt():
    assert [code for code, _, _ in SEED_MODULE.SEED] == PROMPT_CODES


def test_seed_positions_are_one_to_ten():
    assert len(SEED_MODULE.SEED) == 10


def test_only_two_categories_are_manual():
    manual = [code for code, _, auto in SEED_MODULE.SEED if not auto]
    assert manual == ["FOLHA DE PAGAMENTO", "CUSTO DO CARRO"]


def test_codes_are_uppercase_and_labels_are_present():
    for code, label, _ in SEED_MODULE.SEED:
        assert code == code.upper()
        assert label.strip()


def test_category_constraint_names():
    names = {c.name for c in Category.__table__.constraints}
    assert names == {
        "pk_categories",
        "uq_categories_position",
        "ck_categories_code_not_empty",
        "ck_categories_code_uppercase",
        "ck_categories_label_not_empty",
    }
