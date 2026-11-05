"""The User model, with no database (BE-27)."""

import uuid

from server.db import Base, User


def test_user_is_in_the_portal_schema():
    assert User.__table__.schema == "portal"
    assert "portal.users" in Base.metadata.tables


def test_user_id_default_is_uuid4():
    default = User.__table__.c.id.default
    value = default.arg(None)
    assert isinstance(value, uuid.UUID)
    assert value.version == 4


def test_user_repr_shows_only_the_id():
    user = User(id=uuid.uuid4(), access_subject="sub-fulano", email="fulano@exemplo.com")
    text = repr(user)
    assert str(user.id) in text
    assert "fulano" not in text
    assert "@" not in text


def test_user_constraint_names():
    names = {c.name for c in User.__table__.constraints}
    assert names == {
        "pk_users",
        "uq_users_access_subject",
        "uq_users_email",
        "ck_users_email_lowercase",
        "ck_users_access_subject_not_empty",
        "ck_users_email_not_empty",
    }
