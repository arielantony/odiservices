"""Import of a card statement (BE-05): the payload of the extraction that
`ask_pdf.py` asks Claude for, its checks, and the one transaction that stores
it. The field names are the extraction's; the English names of the tables
(BE-28, BE-29) are reached here, once. Nothing here reads a PDF or calls
Anthropic. Messages never carry a value from the payload.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi.responses import JSONResponse
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from server.db import Category, Statement, Transaction, User

MAX_BODY_BYTES = 512 * 1024
MAX_AMOUNT = Decimal("1000000000000")  # an amount is below 10^12
CENT = Decimal("0.01")
SECTIONS = {"compras": "purchases", "internacional": "international", "produtos": "products"}

# (status, code, pt-BR message), spec 3.4 and 3.5.
REFUSED_TOO_LARGE = (413, "payload_too_large", "A fatura enviada é grande demais.")
REFUSED_INVALID = (422, "invalid_statement", "Os dados da fatura são inválidos.")
REFUSED_UNKNOWN_CATEGORY = (
    422,
    "unknown_category",
    "A fatura tem uma categoria desconhecida.",
)
REFUSED_TOTAL = (
    422,
    "total_mismatch",
    "A soma dos lançamentos não confere com o total da fatura.",
)
# GET /api/statements/{id} (BE-10, spec 3.4): one answer for an unknown, a
# malformed and another user's id.
REFUSED_NOT_FOUND = (404, "statement_not_found", "A fatura não foi encontrada.")


class StatementRefused(Exception):
    def __init__(self, refusal: tuple[int, str, str]):
        super().__init__(refusal[1])
        self.refusal = refusal


def refusal_response(refusal: tuple[int, str, str]) -> JSONResponse:
    status, code, message = refusal
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def as_decimal(value: object) -> Decimal:
    """A JSON number, as read_payload parses it: an int, or a Decimal. A string,
    a boolean or a float is not a number here (spec 3.1)."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("not a JSON number")
    return Decimal(value)


def check_money(value: Decimal) -> Decimal:
    if abs(value) >= MAX_AMOUNT or value != value.quantize(CENT):
        raise ValueError("an amount has 2 decimal places at most and is below 10^12")
    return value


def require_text(value: str) -> str:
    if not value.strip():
        raise ValueError("text is empty")
    return value


def require_description(value: str) -> str:
    require_text(value)
    if len(value) > 300:
        raise ValueError("description is longer than 300 characters")
    return value


Money = Annotated[Decimal, BeforeValidator(as_decimal), AfterValidator(check_money)]
Text = Annotated[str, AfterValidator(require_text)]


class Line(BaseModel):
    """One lançamento. Strict: JSON numbers are read as decimals, and no value
    is coerced from another type."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(ge=1)
    secao: Literal["compras", "internacional", "produtos"]
    data: Text
    descricao: Annotated[str, AfterValidator(require_description)]
    valor: Money
    categoria: str
    duvida: bool


class StatementPayload(BaseModel):
    """The body of POST /api/statements (spec 3.1)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    total_lanc_atuais: Money
    lancamentos: list[Line] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "StatementPayload":
        ids = [line.id for line in self.lancamentos]
        if len(set(ids)) != len(ids):
            raise ValueError("ids are not unique")
        return self


def read_payload(raw: bytes) -> StatementPayload:
    """Parse the body. JSON numbers are read as Decimal (parse_float), never as
    binary floats, so a sum is exact. Raises ValueError (bad JSON) or
    ValidationError (a ValueError too) when the body is not a statement."""
    try:
        data = json.loads(raw, parse_float=Decimal)
    except RecursionError as exc:
        raise ValueError("nested too deeply") from exc
    return StatementPayload.model_validate(data)


def lines_total(lines: list[Line]) -> Decimal:
    return sum((line.valor for line in lines), Decimal("0"))


@dataclass(frozen=True)
class Imported:
    id: UUID
    name: str
    total: Decimal
    transaction_count: int
    doubtful_count: int


def import_statement(session: Session, user: User, payload: StatementPayload) -> Imported:
    """Store the statement and its transactions for `user`, all or nothing.
    The category check reads the table (spec 3.2, rule 8); the sum check comes
    after it (rule 9)."""
    codes = set(session.scalars(select(Category.code)))
    lines = payload.lancamentos
    if any(line.categoria not in codes for line in lines):
        raise StatementRefused(REFUSED_UNKNOWN_CATEGORY)
    if lines_total(lines) != payload.total_lanc_atuais:
        raise StatementRefused(REFUSED_TOTAL)

    try:
        statement = Statement(
            user_id=user.id,
            name=payload.name,
            total_lanc_atuais=payload.total_lanc_atuais,
        )
        session.add(statement)
        session.flush()
        statement_id = statement.id
        session.execute(
            insert(Transaction),
            [
                {
                    "statement_id": statement_id,
                    "item_number": line.id,
                    "section": SECTIONS[line.secao],
                    "printed_date": line.data,
                    "description": line.descricao,
                    "amount": line.valor,
                    "category_code": line.categoria,
                    "doubtful": line.duvida,
                    "reviewed": False,
                }
                for line in lines
            ],
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return Imported(
        id=statement_id,
        name=payload.name,
        total=payload.total_lanc_atuais,
        transaction_count=len(lines),
        doubtful_count=sum(line.duvida for line in lines),
    )


class TransactionView(BaseModel):
    """One stored line, as GET /api/statements/{id} returns it (BE-10, spec 3.2).
    Money is a decimal string with two places, never a float."""

    id: str
    item_number: int
    section: str
    printed_date: str
    description: str
    amount: str
    category_code: str
    doubtful: bool
    reviewed: bool


class StatementView(BaseModel):
    """The header and the lines of one statement (BE-10, spec 3.2). The header
    names are BE-05's `201` names, so the import and the read share one shape."""

    id: str
    name: str
    total: str | None
    created_at: str
    transaction_count: int
    doubtful_count: int
    transactions: list[TransactionView]


def money_text(value: Decimal) -> str:
    return f"{value:.2f}"


def utc_text(value: datetime) -> str:
    """ISO 8601 in UTC, ending in `Z` (Pydantic's default would be `+00:00`)."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_statement(session: Session, user: User, statement_id: UUID) -> StatementView | None:
    """The statement `statement_id` and its lines, for `user` only (spec 3.3).
    None when there is no such statement for this user: missing, or another
    user's. The lines are read only after the statement is found."""
    statement = session.scalar(
        select(Statement).where(Statement.id == statement_id, Statement.user_id == user.id)
    )
    if statement is None:
        return None
    transactions = list(
        session.scalars(
            select(Transaction)
            .where(Transaction.statement_id == statement.id)
            .order_by(Transaction.item_number)
        )
    )
    return StatementView(
        id=str(statement.id),
        name=statement.name,
        total=None if statement.total_lanc_atuais is None else money_text(statement.total_lanc_atuais),
        created_at=utc_text(statement.created_at),
        transaction_count=len(transactions),
        doubtful_count=sum(1 for item in transactions if item.doubtful),
        transactions=[
            TransactionView(
                id=str(item.id),
                item_number=item.item_number,
                section=item.section,
                printed_date=item.printed_date,
                description=item.description,
                amount=money_text(item.amount),
                category_code=item.category_code,
                doubtful=item.doubtful,
                reviewed=item.reviewed,
            )
            for item in transactions
        ],
    )
