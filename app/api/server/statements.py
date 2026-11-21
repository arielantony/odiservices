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
from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.db import Category, Statement, Transaction, User

MAX_BODY_BYTES = 512 * 1024
MAX_PATCH_BYTES = 1024  # PATCH of one transaction (BE-11, spec 3.2)
CATEGORY_CONSTRAINT = "fk_transactions_category_code_categories"  # base.py naming
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
# PATCH .../transactions/{transaction_id} (BE-11, spec 3.4).
REFUSED_TRANSACTION_NOT_FOUND = (
    404,
    "transaction_not_found",
    "A transação não foi encontrada.",
)


# The processing status and the failure codes of a statement (BE-07, spec 3.4).
# The codes are checked in SQL by migration 0008; the messages are read after
# "Falhou: " by the frontend (FE-04).
STATUSES = ("processing", "ready", "failed")
FAILURE_MESSAGES = {
    "invalid_pdf": "PDF ilegível",
    "extraction_unavailable": "o serviço de leitura está indisponível",
    "extraction_timeout": "a leitura demorou demais",
    "extraction_refused": "a leitura da fatura foi recusada",
    "extraction_truncated": "a leitura da fatura ficou incompleta",
    "extraction_invalid": "não foi possível ler a fatura",
    "unknown_category": "há uma categoria desconhecida na fatura",
    "total_mismatch": "a soma dos lançamentos não confere com o total",
    "interrupted": "a leitura foi interrompida",
    "upload_not_available": "o arquivo enviado não está mais disponível",
    "unknown": "erro inesperado",
}
FAILURE_CODES = tuple(FAILURE_MESSAGES)


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
    # The card (BE-09, spec 3.1): optional, absent and null mean the same.
    cartao_nome: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
    ] = None
    cartao_final: Annotated[str | None, StringConstraints(pattern=r"^[0-9]{4}$")] = None

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


class TransactionPatch(BaseModel):
    """The body of PATCH .../transactions/{transaction_id} (BE-11, spec 3.2). At
    least one field, none of them null. `doubtful` is not a field: no route
    changes it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category_code: str | None = None
    reviewed: bool | None = None

    @model_validator(mode="after")
    def some_field_and_no_null(self) -> "TransactionPatch":
        if not self.model_fields_set:
            raise ValueError("no field to change")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("a field is null")
        return self


def read_patch(raw: bytes) -> TransactionPatch:
    """Parse the body. Raises ValueError (bad JSON) or ValidationError (a
    ValueError too) when the body is not a valid change."""
    try:
        data = json.loads(raw)
    except RecursionError as exc:
        raise ValueError("nested too deeply") from exc
    return TransactionPatch.model_validate(data)


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
            card_name=payload.cartao_nome,
            card_last4=payload.cartao_final,
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
                    "original_category_code": line.categoria,
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
    moved_by_user: bool


class StatementView(BaseModel):
    """The header and the lines of one statement (BE-10, spec 3.2). The header
    names are BE-05's `201` names, so the import and the read share one shape."""

    id: str
    name: str
    status: str  # BE-07, spec 3.3: processing, ready or failed
    failure_code: str | None  # BE-07: null unless status is failed
    failure_message: str | None  # BE-07: the pt-BR reason of failure_code
    card_name: str | None  # BE-09, spec 3.4: null when the statement has no card
    card_last4: str | None
    total: str | None
    created_at: str
    transaction_count: int
    doubtful_count: int
    pending_review_count: int  # doubtful and not reviewed (BE-11, spec 3.6)
    transactions: list[TransactionView]


def money_text(value: Decimal) -> str:
    return f"{value:.2f}"


def utc_text(value: datetime) -> str:
    """ISO 8601 in UTC, ending in `Z` (Pydantic's default would be `+00:00`)."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def transaction_view(item: Transaction) -> TransactionView:
    return TransactionView(
        id=str(item.id),
        item_number=item.item_number,
        section=item.section,
        printed_date=item.printed_date,
        description=item.description,
        amount=money_text(item.amount),
        category_code=item.category_code,
        doubtful=item.doubtful,
        reviewed=item.reviewed,
        moved_by_user=item.category_code != item.original_category_code,
    )


def owned_statement(session: Session, user: User, statement_id: UUID) -> Statement | None:
    """The statement `statement_id` if it belongs to `user`, else None: missing
    and another user's are the same answer (BE-10, BE-11 step 2)."""
    return session.scalar(
        select(Statement).where(Statement.id == statement_id, Statement.user_id == user.id)
    )


def read_statement(session: Session, user: User, statement_id: UUID) -> StatementView | None:
    """The statement `statement_id` and its lines, for `user` only (spec 3.3).
    None when there is no such statement for this user: missing, or another
    user's. The lines are read only after the statement is found."""
    statement = owned_statement(session, user, statement_id)
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
        status=statement.status,
        failure_code=statement.failure_code,
        failure_message=(
            None if statement.failure_code is None else FAILURE_MESSAGES[statement.failure_code]
        ),
        card_name=statement.card_name,
        card_last4=statement.card_last4,
        total=None if statement.total_lanc_atuais is None else money_text(statement.total_lanc_atuais),
        created_at=utc_text(statement.created_at),
        transaction_count=len(transactions),
        doubtful_count=sum(1 for item in transactions if item.doubtful),
        pending_review_count=sum(
            1 for item in transactions if item.doubtful and not item.reviewed
        ),
        transactions=[transaction_view(item) for item in transactions],
    )


def update_transaction(
    session: Session,
    user: User,
    statement_id: UUID,
    transaction_id: UUID,
    patch: TransactionPatch,
) -> TransactionView:
    """Set the sent fields of one line (BE-11, spec 3.1 steps 6 to 9). The caller
    has already checked that `statement_id` is `user`'s. Only the values that
    differ are written: a request that changes nothing executes no UPDATE, so
    `updated_at` stays. `doubtful` is never written."""
    item = session.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id, Transaction.statement_id == statement_id)
        .with_for_update()
    )
    if item is None:
        session.rollback()
        raise StatementRefused(REFUSED_TRANSACTION_NOT_FOUND)
    if patch.category_code is not None and session.scalar(
        select(Category.code).where(Category.code == patch.category_code)
    ) is None:
        session.rollback()
        raise StatementRefused(REFUSED_UNKNOWN_CATEGORY)

    requested = {"category_code": patch.category_code, "reviewed": patch.reviewed}
    for name, value in requested.items():
        if value is not None and getattr(item, name) != value:
            setattr(item, name, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig.diag, "constraint_name", None) == CATEGORY_CONSTRAINT:
            raise StatementRefused(REFUSED_UNKNOWN_CATEGORY) from None
        raise
    return transaction_view(item)


class CategoryTotalView(BaseModel):
    """One category of a statement, as GET .../summary returns it (BE-12, spec
    3.2). Money is a decimal string with two places; share is an integer."""

    category_code: str
    position: int
    total: str
    transaction_count: int
    pending_review_count: int
    share: int | None


class CategorySummaryView(BaseModel):
    """The per-category summary of one statement (BE-12, spec 3.2)."""

    lines_total: str
    positive_total: str
    categories: list[CategoryTotalView]


@dataclass(frozen=True)
class CategoryRow:
    code: str
    position: int
    total: Decimal
    count: int
    pending: int


def category_totals(session: Session, statement_id: UUID) -> list:
    """One row per category, with its total, line count and pending count for the
    statement (spec 3.3). The statement filter is in the join, so a category with
    no lines still has its row."""
    return session.execute(
        select(
            Category.code,
            Category.position,
            func.coalesce(func.sum(Transaction.amount), 0),
            func.count(Transaction.id),
            func.count(Transaction.id).filter(
                Transaction.doubtful.is_(True), Transaction.reviewed.is_(False)
            ),
        )
        .select_from(Category)
        .outerjoin(
            Transaction,
            and_(
                Transaction.category_code == Category.code,
                Transaction.statement_id == statement_id,
            ),
        )
        .group_by(Category.code, Category.position)
    ).all()


def summary_view(rows) -> CategorySummaryView:
    """The categories ordered by total, descending, ties by position ascending, with
    the shares by the largest-remainder rule (spec 3.3). `rows` holds
    (code, position, total, count, pending); the work is over at most ten rows."""
    ordered = sorted(
        (
            CategoryRow(code, position, Decimal(total), int(count), int(pending))
            for code, position, total, count, pending in rows
        ),
        key=lambda row: (-row.total, row.position),
    )
    positive = [row for row in ordered if row.total > 0]
    positive_total = sum((row.total for row in positive), Decimal("0"))

    shares: dict[str, int] = {}
    if positive_total > 0:
        exact = {row.code: row.total * 100 / positive_total for row in positive}
        floors = {code: int(value) for code, value in exact.items()}
        remainders = {code: value - floors[code] for code, value in exact.items()}
        deficit = 100 - sum(floors.values())
        by_remainder = sorted(
            positive, key=lambda row: (-remainders[row.code], row.position)
        )
        extra = {row.code for row in by_remainder[:deficit]}
        shares = {code: floor + (code in extra) for code, floor in floors.items()}

    return CategorySummaryView(
        lines_total=money_text(sum((row.total for row in ordered), Decimal("0"))),
        positive_total=money_text(positive_total),
        categories=[
            CategoryTotalView(
                category_code=row.code,
                position=row.position,
                total=money_text(row.total),
                transaction_count=row.count,
                pending_review_count=row.pending,
                share=shares.get(row.code),
            )
            for row in ordered
        ],
    )


def set_status(
    session: Session,
    statement_id: UUID,
    status: str,
    failure_code: str | None = None,
    *,
    expected: str | None = None,
    commit: bool = True,
) -> bool:
    """Set the processing status of a statement (BE-07, spec 3.5). Internal: no
    route calls it. True when a row was updated, False when none matched (a
    missing id, or a status other than `expected`). The refusals name the
    argument, never its value. The order of the states is the caller's rule."""
    if status not in STATUSES:
        raise ValueError("status is not a known status")
    if status == "failed" and failure_code is None:
        raise ValueError("failure_code is required when status is failed")
    if status != "failed" and failure_code is not None:
        raise ValueError("failure_code is only set when status is failed")
    if failure_code is not None and failure_code not in FAILURE_CODES:
        raise ValueError("failure_code is not a known code")

    statement = update(Statement).where(Statement.id == statement_id)
    if expected is not None:
        statement = statement.where(Statement.status == expected)
    result = session.execute(
        statement.values(status=status, failure_code=failure_code, updated_at=func.now())
    )
    if commit:
        session.commit()
    return result.rowcount == 1


def read_category_summary(
    session: Session, user: User, statement_id: UUID
) -> CategorySummaryView | None:
    """The per-category summary of `statement_id`, for `user` only (spec 3.5). None
    when there is no such statement for this user. The totals are read only after
    the statement is found."""
    if owned_statement(session, user, statement_id) is None:
        return None
    return summary_view(category_totals(session, statement_id))
