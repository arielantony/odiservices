"""The Statement model, with no database (BE-28)."""

import uuid
from decimal import Decimal

from sqlalchemy import CHAR, Numeric, Text

from server.db import Base, Statement

NAME = "Fatura Cartão Exemplo, set/2026"


def test_statement_is_in_the_portal_schema():
    assert Statement.__table__.schema == "portal"
    assert "portal.statements" in Base.metadata.tables


def test_statement_id_default_is_uuid4():
    default = Statement.__table__.c.id.default
    value = default.arg(None)
    assert isinstance(value, uuid.UUID)
    assert value.version == 4


def test_statement_repr_shows_only_the_id():
    statement = Statement(id=uuid.uuid4(), user_id=uuid.uuid4(), name=NAME)
    text = repr(statement)
    assert str(statement.id) in text
    assert "Fatura" not in text
    assert "set/2026" not in text


def test_statement_total_is_numeric_and_nullable():
    column = Statement.__table__.c.total_lanc_atuais
    assert isinstance(column.type, Numeric)
    assert (column.type.precision, column.type.scale) == (14, 2)
    assert column.nullable is True
    assert Statement(user_id=uuid.uuid4(), name=NAME).total_lanc_atuais is None
    assert Decimal("11906.35") == Statement(
        user_id=uuid.uuid4(), name=NAME, total_lanc_atuais=Decimal("11906.35")
    ).total_lanc_atuais


def test_card_columns_are_declared():
    name = Statement.__table__.c.card_name
    last4 = Statement.__table__.c.card_last4
    assert isinstance(name.type, Text) and name.nullable is True
    assert isinstance(last4.type, CHAR) and last4.type.length == 4 and last4.nullable is True


def test_repr_does_not_show_card():
    statement = Statement(
        id=uuid.UUID("6f1c0e2a-9b7d-4c1e-8a55-2d3f4b6a7c10"),
        user_id=uuid.uuid4(),
        name=NAME,
        card_name="Cartão Sigilo Exemplo",
        card_last4="9876",
    )
    text = repr(statement)
    assert str(statement.id) in text
    assert "Sigilo" not in text
    assert "9876" not in text
