"""ORM models. Every table lives in the `portal` schema (see base.py)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, func, text
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
