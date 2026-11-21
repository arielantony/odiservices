"""transaction_view and the moved_by_user flag, with no database (BE-13). The
transactions are ORM objects that are never added to a session."""

import uuid
from decimal import Decimal

from server.db import Transaction
from server.statements import transaction_view


def line(category_code: str, original_category_code: str) -> Transaction:
    return Transaction(
        id=uuid.uuid4(),
        statement_id=uuid.uuid4(),
        item_number=8,
        section="products",
        printed_date="05/09",
        description="Notebook Loja Fictícia",
        amount=Decimal("4899.00"),
        category_code=category_code,
        original_category_code=original_category_code,
        doubtful=False,
        reviewed=False,
    )


def test_moved_by_user_compares_the_two_categories():
    moved = transaction_view(line("OPERACIONAL", "FORNECEDOR"))
    unchanged = transaction_view(line("FORNECEDOR", "FORNECEDOR"))

    assert moved.moved_by_user is True
    assert unchanged.moved_by_user is False


def test_moved_by_user_is_always_a_bool():
    for item in (line("OPERACIONAL", "FORNECEDOR"), line("OUTROS", "OUTROS")):
        dumped = transaction_view(item).model_dump()
        assert "moved_by_user" in dumped
        assert dumped["moved_by_user"] in (True, False)
        assert type(dumped["moved_by_user"]) is bool
