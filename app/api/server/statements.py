"""Import of a card statement (BE-05): the payload of the extraction that
`ask_pdf.py` asks Claude for, its checks, and the one transaction that stores
it. The field names are the extraction's; the English names of the tables
(BE-28, BE-29) are reached here, once. Nothing here reads a PDF or calls
Anthropic. Messages never carry a value from the payload.
"""

import base64
import json
import re
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
from sqlalchemy import and_, delete, func, insert, or_, select, update
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
# GET /api/statements (BE-06, spec 3.6): the page size and the cursor.
REFUSED_INVALID_LIMIT = (
    422,
    "invalid_limit",
    "O tamanho da página deve ser um número entre 1 e 100.",
)
REFUSED_INVALID_CURSOR = (422, "invalid_cursor", "O cursor da página não é válido.")
# GET .../export (BE-14, spec 3.5): a statement BE-05 could not have stored.
REFUSED_NOT_EXPORTABLE = (
    409,
    "statement_not_exportable",
    "Esta fatura não pode ser exportada: ela não tem lançamentos ou um total.",
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


def check_payload(session: Session, payload: StatementPayload) -> None:
    """Rules 8 and 9 of BE-05 (spec 3.4): the categories, read from the table, then
    the sum. Raises StatementRefused. Writes nothing."""
    codes = set(session.scalars(select(Category.code)))
    lines = payload.lancamentos
    if any(line.categoria not in codes for line in lines):
        raise StatementRefused(REFUSED_UNKNOWN_CATEGORY)
    if lines_total(lines) != payload.total_lanc_atuais:
        raise StatementRefused(REFUSED_TOTAL)


def store_lines(session: Session, statement: Statement, payload: StatementPayload) -> Imported:
    """Set the statement's total and insert its transactions, in one insert. Does
    not commit: the caller owns the transaction (spec 3.4)."""
    lines = payload.lancamentos
    statement.total_lanc_atuais = payload.total_lanc_atuais
    session.execute(
        insert(Transaction),
        [
            {
                "statement_id": statement.id,
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
    return Imported(
        id=statement.id,
        name=payload.name,
        total=payload.total_lanc_atuais,
        transaction_count=len(lines),
        doubtful_count=sum(line.duvida for line in lines),
    )


def import_statement(session: Session, user: User, payload: StatementPayload) -> Imported:
    """Store the statement and its transactions for `user`, all or nothing.
    The category check reads the table (spec 3.2, rule 8); the sum check comes
    after it (rule 9)."""
    check_payload(session, payload)
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
        imported = store_lines(session, statement, payload)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return imported


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


# GET /api/statements (BE-06, spec 3.2 to 3.4): the statements of one user,
# newest first, one keyset page at a time.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 512
CURSOR_VERSION = 1
LIMIT_PATTERN = re.compile(r"[0-9]{1,3}")


def parse_limit(values: list[str]) -> int:
    """The `limit` query parameter: absent is the default; one value of 1 to 100.
    Anything else raises ValueError (the route answers invalid_limit)."""
    if not values:
        return DEFAULT_LIMIT
    if len(values) != 1 or LIMIT_PATTERN.fullmatch(values[0]) is None:
        raise ValueError("limit is not a number")
    limit = int(values[0])
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit is out of range")
    return limit


def encode_cursor(created_at: datetime, statement_id: UUID) -> str:
    """The opaque cursor of a row: its full-precision created_at (UTC) and id,
    as URL-safe base64 of UTF-8 JSON, without padding (spec 3.3)."""
    body = {
        "v": CURSOR_VERSION,
        "t": created_at.astimezone(timezone.utc).isoformat(),
        "i": str(statement_id),
    }
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def parse_cursor(value: str) -> tuple[datetime, UUID]:
    """The position a cursor names. Every step must hold (spec 3.3): any failure
    raises ValueError, and nothing from the cursor is echoed."""
    if len(value) > MAX_CURSOR_LENGTH:
        raise ValueError("cursor is too long")
    padded = value + "=" * (-len(value) % 4)
    raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"v", "t", "i"}:
        raise ValueError("cursor has the wrong keys")
    if type(data["v"]) is not int or data["v"] != CURSOR_VERSION:
        raise ValueError("cursor version is not known")
    if not isinstance(data["t"], str) or not isinstance(data["i"], str):
        raise ValueError("cursor values are not text")
    moment = datetime.fromisoformat(data["t"])
    if moment.utcoffset() is None:
        raise ValueError("cursor time has no UTC offset")
    return moment, UUID(data["i"])


class StatementListItemView(BaseModel):
    """One statement of the list (BE-06, spec 3.2 and its amendment). The header
    fields and their types are BE-10's, so the list and the read share one shape."""

    id: str
    name: str
    status: str  # BE-07
    failure_code: str | None  # BE-07
    failure_message: str | None  # BE-07
    card_name: str | None  # BE-09
    card_last4: str | None  # BE-09
    total: str | None
    created_at: str
    transaction_count: int
    pending_review_count: int


class StatementPageView(BaseModel):
    """One page of statements, newest first (BE-06, spec 3.2)."""

    items: list[StatementListItemView]
    next_cursor: str | None


def list_item_view(row) -> StatementListItemView:
    return StatementListItemView(
        id=str(row.id),
        name=row.name,
        status=row.status,
        failure_code=row.failure_code,
        failure_message=(
            None if row.failure_code is None else FAILURE_MESSAGES[row.failure_code]
        ),
        card_name=row.card_name,
        card_last4=row.card_last4,
        total=None if row.total_lanc_atuais is None else money_text(row.total_lanc_atuais),
        created_at=utc_text(row.created_at),
        transaction_count=row.transaction_count,
        pending_review_count=row.pending_review_count,
    )


def read_statement_page(
    session: Session, user: User, limit: int, after: tuple[datetime, UUID] | None
) -> StatementPageView:
    """The page of `user`'s statements after `after` (spec 3.4). The page is
    limited before the join, so the counts run over the page's lines only, and
    one statement reads the page and its counts. Fetches limit + 1 rows: the
    extra one only decides next_cursor. Never None: an empty page is an answer."""
    page = select(
        Statement.id,
        Statement.name,
        Statement.total_lanc_atuais,
        Statement.card_name,
        Statement.card_last4,
        Statement.status,
        Statement.failure_code,
        Statement.created_at,
    ).where(Statement.user_id == user.id)
    if after is not None:
        moment, last_id = after
        page = page.where(
            or_(
                Statement.created_at < moment,
                and_(Statement.created_at == moment, Statement.id < last_id),
            )
        )
    page = page.order_by(Statement.created_at.desc(), Statement.id.desc())
    page = page.limit(limit + 1).subquery("page")

    columns = [
        page.c.id,
        page.c.name,
        page.c.total_lanc_atuais,
        page.c.card_name,
        page.c.card_last4,
        page.c.status,
        page.c.failure_code,
        page.c.created_at,
    ]
    rows = list(
        session.execute(
            select(
                *columns,
                func.count(Transaction.id).label("transaction_count"),
                func.count(Transaction.id)
                .filter(Transaction.doubtful.is_(True), Transaction.reviewed.is_(False))
                .label("pending_review_count"),
            )
            .select_from(page)
            .outerjoin(Transaction, Transaction.statement_id == page.c.id)
            .group_by(*columns)
            .order_by(page.c.created_at.desc(), page.c.id.desc())
        ).all()
    )
    kept = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = kept[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return StatementPageView(items=[list_item_view(row) for row in kept], next_cursor=next_cursor)


# GET /api/statements/{id}/export (BE-14, spec 3.2 to 3.3): the statement as the
# file that POST /api/statements (BE-05) imports. The inverse of SECTIONS, built
# from it so the two maps cannot drift.
SECTIONS_OUT = {english: portuguese for portuguese, english in SECTIONS.items()}


def export_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_export(
    name: str,
    total: Decimal,
    lines,
    *,
    card_name: str | None = None,
    card_last4: str | None = None,
) -> bytes:
    """The export file of spec 3.3, as text: money is an unquoted JSON number, so
    BE-05 reads it as a Decimal. `lines` are stored transactions. Pure: no
    database. The card keys are written only when the statement has them (BE-14
    amendment)."""
    head = [f'"name": {export_text(name)}']
    if card_name is not None:
        head.append(f'"cartao_nome": {export_text(card_name)}')
    if card_last4 is not None:
        head.append(f'"cartao_final": {export_text(card_last4)}')
    head.append(f'"total_lanc_atuais": {money_text(total)}')
    items = [
        f'{{"id": {item.item_number}, "secao": {export_text(SECTIONS_OUT[item.section])}, '
        f'"data": {export_text(item.printed_date)}, '
        f'"descricao": {export_text(item.description)}, '
        f'"valor": {money_text(item.amount)}, '
        f'"categoria": {export_text(item.category_code)}, '
        f'"duvida": {"true" if item.doubtful else "false"}}}'
        for item in lines
    ]
    body = "{" + ", ".join(head) + ', "lancamentos": [' + ",\n  ".join(items) + "]}"
    return body.encode("utf-8")


def read_export(session: Session, user: User, statement_id: UUID) -> bytes | None:
    """The export file of `statement_id`, for `user` only (spec 3.2). None when
    there is no such statement for this user. Refuses (StatementRefused, 409) a
    statement that BE-05 could not have stored: not ready, no total, no line, or
    a sum that does not match the total. The lines are read only after the
    statement is found."""
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
    if (
        statement.status != "ready"
        or statement.total_lanc_atuais is None
        or not transactions
        or sum((item.amount for item in transactions), Decimal("0"))
        != statement.total_lanc_atuais
    ):
        raise StatementRefused(REFUSED_NOT_EXPORTABLE)
    return render_export(
        statement.name,
        statement.total_lanc_atuais,
        transactions,
        card_name=statement.card_name,
        card_last4=statement.card_last4,
    )


def delete_statement(session: Session, user: User, statement_id: UUID) -> bool:
    """Delete `statement_id` for `user` only (BE-15, spec 3.3). One DELETE is the
    ownership check and the delete together. The lines go with the statement by
    ON DELETE CASCADE, in the same transaction. True when a row was deleted; False
    when none matched (missing, already deleted, or another user's)."""
    try:
        result = session.execute(
            delete(Statement)
            .where(Statement.id == statement_id, Statement.user_id == user.id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            session.commit()
            return True
        session.rollback()
        return False
    except Exception:
        session.rollback()
        raise
