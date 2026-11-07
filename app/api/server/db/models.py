"""ORM models. Every table lives in the `portal` schema (see base.py)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, func, text
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
