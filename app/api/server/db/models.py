"""ORM models. Every table lives in the `portal` schema (see base.py)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.db.base import Base


class User(Base):
    """A person who signed in through Cloudflare Access (BE-27).

    A row says who someone is, never what they may do. It is found by
    `access_subject`, the Access `sub`: the email can change, the subject
    does not."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("access_subject <> ''", name="access_subject_not_empty"),
        CheckConstraint("email <> ''", name="email_not_empty"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    access_subject: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # The id only: a user printed by mistake must not leak the email.
        return f"<User {self.id}>"


class Category(Base):
    """A category a transaction can have (BE-30). A lookup table: the
    transactions refer to `code` by a foreign key (BE-29), and the set changes
    only by migration or by SQL run by the owner."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("code <> ''", name="code_not_empty"),
        CheckConstraint("code = upper(code)", name="code_uppercase"),
        CheckConstraint("label <> ''", name="label_not_empty"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    auto_assign: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    position: Mapped[int] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Category {self.code}>"


class Statement(Base):
    """A card statement (fatura) a person sent (BE-28). One row per statement;
    the transactions refer to it by a foreign key (BE-29)."""

    __tablename__ = "statements"
    __table_args__ = (
        CheckConstraint("name <> ''", name="name_not_empty"),
        Index("ix_statements_user_id_created_at", "user_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(Text)
    total_lanc_atuais: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # The id only: the name can reveal a card or a month.
        return f"<Statement {self.id}>"


class Transaction(Base):
    """One line of a card statement (a lançamento), BE-29. It belongs to a
    statement (deleted with it) and has a category from the fixed set (BE-30)."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("statement_id", "item_number"),
        CheckConstraint("item_number >= 1", name="item_number_positive"),
        CheckConstraint(
            "section in ('purchases', 'international', 'products')", name="section_known"
        ),
        CheckConstraint("printed_date <> ''", name="printed_date_not_empty"),
        CheckConstraint("description <> ''", name="description_not_empty"),
        Index("ix_transactions_statement_id_category_code", "statement_id", "category_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE")
    )
    item_number: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    printed_date: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category_code: Mapped[str] = mapped_column(
        ForeignKey("categories.code", ondelete="RESTRICT")
    )
    doubtful: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    reviewed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # The id only: the description names merchants.
        return f"<Transaction {self.id}>"
