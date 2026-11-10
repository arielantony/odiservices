"""The Transaction model, with no database (BE-29)."""

import uuid
from decimal import Decimal

from sqlalchemy import Numeric

from server.db import Base, Transaction

DESCRIPTION = "LOJA EXEMPLO 1/3"


def test_transaction_is_in_the_portal_schema():
    assert Transaction.__table__.schema == "portal"
    assert "portal.transactions" in Base.metadata.tables


def test_transaction_id_default_is_uuid4():
    default = Transaction.__table__.c.id.default
    value = default.arg(None)
    assert isinstance(value, uuid.UUID)
    assert value.version == 4


def test_transaction_repr_shows_only_the_id():
    transaction = Transaction(
        id=uuid.uuid4(),
        statement_id=uuid.uuid4(),
        item_number=1,
        section="purchases",
        printed_date="03/09",
        description=DESCRIPTION,
        amount=Decimal("-49.90"),
        category_code="OUTROS",
    )
    text = repr(transaction)
    assert str(transaction.id) in text
    assert "LOJA" not in text
    assert "EXEMPLO" not in text


def test_transaction_amount_is_numeric():
    column = Transaction.__table__.c.amount
    assert isinstance(column.type, Numeric)
    assert (column.type.precision, column.type.scale) == (14, 2)
    assert column.nullable is False
