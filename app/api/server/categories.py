"""The categories and their pt-BR labels (BE-16). The table is BE-30's; this
module only reads it, in the order of its position."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import Category


class CategoryView(BaseModel):
    """The only shape the categories route returns (spec 3.4). A column added
    to the table later is not exposed by accident."""

    code: str
    label: str
    position: int


def list_categories(session: Session) -> list[CategoryView]:
    # The order is set in SQL: the database owns the position (spec 9).
    rows = session.scalars(select(Category).order_by(Category.position)).all()
    return [CategoryView(code=r.code, label=r.label, position=r.position) for r in rows]
