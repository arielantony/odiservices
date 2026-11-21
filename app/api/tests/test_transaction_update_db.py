"""PATCH /api/statements/{id}/transactions/{id} against a real Postgres (BE-11). Run
by make test-db; the app connects as app_backend. The statements are imported
through import_statement (BE-05) and read through GET (BE-10)."""

import uuid

import pytest
from sqlalchemy import text

from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    owner,
    url,
)
from test_statement_payload import NAME, extract
from test_statement_read_db import (  # noqa: F401  (fixtures and helpers)
    client,
    engine,
    gap_payload,
    get,
    import_for,
    person,
)

pytestmark = pytest.mark.db


def patch(client, statement_id, transaction_id, body, headers):
    url_path = f"/api/statements/{statement_id}/transactions/{transaction_id}"
    return client.patch(url_path, json=body, headers=headers)


def lines_of(client, statement_id, headers) -> list[dict]:
    return get(client, statement_id, headers).json()["transactions"]


def line(client, statement_id, headers, description) -> dict:
    return next(
        item
        for item in lines_of(client, statement_id, headers)
        if item["description"] == description
    )


def updated_at(migrated, transaction_id: str):
    """The stored updated_at, read as the owner."""
    with owner(migrated).connect() as connection:
        return connection.execute(
            text("select updated_at from portal.transactions where id = :id"),
            {"id": uuid.UUID(transaction_id)},
        ).scalar_one()


def test_confirm_sets_reviewed_and_keeps_doubt(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    before = line(client, imported.id, headers, "Software Gestão Teste")

    response = patch(client, imported.id, before["id"], {"reviewed": True}, headers)

    assert response.status_code == 200
    after = response.json()
    assert after["reviewed"] is True
    assert after["doubtful"] is True
    assert after["category_code"] == before["category_code"]


def test_undo_confirm_makes_it_pending_again(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    doubt = line(client, imported.id, headers, "Software Gestão Teste")
    assert get(client, imported.id, headers).json()["pending_review_count"] == 2
    patch(client, imported.id, doubt["id"], {"reviewed": True}, headers)
    assert get(client, imported.id, headers).json()["pending_review_count"] == 1

    response = patch(client, imported.id, doubt["id"], {"reviewed": False}, headers)

    assert response.status_code == 200
    assert response.json()["doubtful"] is True
    assert response.json()["reviewed"] is False
    data = get(client, imported.id, headers).json()
    assert data["pending_review_count"] == 2
    assert data["doubtful_count"] == 2


def test_move_then_undo_restores_both_fields(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    before = next(item for item in lines_of(client, imported.id, headers) if not item["doubtful"])
    target = "OPERACIONAL" if before["category_code"] != "OPERACIONAL" else "OUTROS"

    moved = patch(
        client, imported.id, before["id"],
        {"category_code": target, "reviewed": True}, headers,
    )
    assert moved.status_code == 200
    assert moved.json()["category_code"] == target
    assert moved.json()["reviewed"] is True

    undone = patch(
        client, imported.id, before["id"],
        {"category_code": before["category_code"], "reviewed": before["reviewed"]}, headers,
    )

    assert undone.status_code == 200
    assert line(client, imported.id, headers, before["description"]) == before


def test_unknown_category_stores_nothing(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    before = line(client, imported.id, headers, "Software Gestão Teste")

    response = patch(client, imported.id, before["id"], {"category_code": "NAO EXISTE"}, headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_category"
    assert line(client, imported.id, headers, "Software Gestão Teste") == before


def test_other_users_statement_is_identical_to_missing(client, engine):
    owner_id, owner_headers = person(client)
    imported = import_for(engine, owner_id, {"name": NAME, **extract()})
    transaction_id = line(client, imported.id, owner_headers, "Software Gestão Teste")["id"]
    _, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")
    without_id = lambda response: {  # noqa: E731
        key: value for key, value in response.headers.items() if key != "x-request-id"
    }

    for body in ({"reviewed": True}, {"reviewed": "true"}):
        other = patch(client, imported.id, transaction_id, body, other_headers)
        missing = patch(client, uuid.uuid4(), transaction_id, body, other_headers)

        assert other.status_code == missing.status_code == 404
        assert other.content == missing.content
        assert without_id(other) == without_id(missing)
    owner_change = patch(client, imported.id, transaction_id, {"reviewed": True}, owner_headers)
    assert owner_change.status_code == 200


def test_transaction_of_another_statement_is_404(client, engine):
    user_id, headers = person(client)
    first = import_for(engine, user_id, {"name": NAME, **extract()})
    second = import_for(engine, user_id, gap_payload())
    transaction_id = lines_of(client, second.id, headers)[0]["id"]

    response = patch(client, first.id, transaction_id, {"reviewed": True}, headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"


def test_same_values_do_not_touch_updated_at(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    transaction_id = line(client, imported.id, headers, "Software Gestão Teste")["id"]
    patch(client, imported.id, transaction_id, {"reviewed": True}, headers)
    first = updated_at(migrated, transaction_id)

    response = patch(client, imported.id, transaction_id, {"reviewed": True}, headers)

    assert response.status_code == 200
    assert updated_at(migrated, transaction_id) == first


def test_change_moves_updated_at(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    transaction_id = line(client, imported.id, headers, "Software Gestão Teste")["id"]
    patch(client, imported.id, transaction_id, {"reviewed": True}, headers)
    first = updated_at(migrated, transaction_id)

    patch(client, imported.id, transaction_id, {"reviewed": False}, headers)

    assert updated_at(migrated, transaction_id) > first
