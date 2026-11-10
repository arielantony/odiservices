"""The Statement model, with no database (BE-28)."""

import uuid
from decimal import Decimal

from sqlalchemy import Numeric

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
