"""GET /api/statements against a real Postgres (BE-06). Run by make test-db; the
app connects as app_backend. The statements are imported through import_statement
(BE-05) or inserted through the ORM with explicit created_at values, so the page
sees what the import writes."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from server.db import Statement, Transaction
from server.statements import set_status
from test_statement_payload import NAME, extract
from test_statement_read_db import client, engine, import_for, person  # noqa: F401  (fixtures)
from test_migrations_db import (  # noqa: F401  (fixtures)
    database,
    migrated,
    url,
)

pytestmark = pytest.mark.db

BASE = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def add_statements(engine, user_id: str, count: int, step=timedelta(hours=1), lines=0, start=BASE):
    """`count` statements of `user_id`, oldest first, each `step` after the last.
    Each gets `lines` transactions. Returns the ids in creation order."""
    ids = []
    with Session(engine) as session:
        for number in range(count):
            statement = Statement(
                user_id=uuid.UUID(user_id),
                name=f"Fatura Demo Exemplo, nº {number:02d}",
                created_at=start + step * number,
            )
            session.add(statement)
            session.flush()
            session.add_all(
                Transaction(
                    statement_id=statement.id,
                    item_number=line,
                    section="purchases",
                    printed_date="05/09",
                    description="Loja Exemplo",
                    amount=Decimal("10.00"),
                    category_code="OUTROS",
                    original_category_code="OUTROS",
                    doubtful=False,
                    reviewed=False,
                )
                for line in range(1, lines + 1)
            )
            ids.append(str(statement.id))
        session.commit()
    return ids


def walk(client, headers, limit: int, cursor=None) -> list[dict]:
    """Every page from the first (or from `cursor`), until next_cursor is null."""
    pages = []
    while True:
        query = f"?limit={limit}" + (f"&cursor={cursor}" if cursor else "")
        response = client.get(f"/api/statements{query}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        pages.append(data)
        cursor = data["next_cursor"]
        if cursor is None:
            return pages


def ids_of(pages: list[dict]) -> list[str]:
    return [item["id"] for page in pages for item in page["items"]]


def test_newest_first_across_pages(client, engine):
    user_id, headers = person(client)
    ids = add_statements(engine, user_id, 45)

    pages = walk(client, headers, 20)

    assert [len(page["items"]) for page in pages] == [20, 20, 5]
    assert pages[-1]["next_cursor"] is None
    assert ids_of(pages) == list(reversed(ids))


def test_equal_created_at_is_ordered_by_id(client, engine):
    user_id, headers = person(client)
    ids = add_statements(engine, user_id, 3, step=timedelta(0))

    pages = walk(client, headers, 1)

    assert ids_of(pages) == sorted(ids, key=uuid.UUID, reverse=True)
    assert len(pages) == 3


def test_exact_page_has_no_next_cursor(client, engine):
    user_id, headers = person(client)
    add_statements(engine, user_id, 20)

    (full,) = walk(client, headers, 20)
    assert len(full["items"]) == 20
    assert full["next_cursor"] is None

    add_statements(engine, user_id, 1, start=BASE + timedelta(days=1))
    first = client.get("/api/statements?limit=20", headers=headers).json()
    assert len(first["items"]) == 20
    assert isinstance(first["next_cursor"], str)
    second = client.get(
        f"/api/statements?limit=20&cursor={first['next_cursor']}", headers=headers
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None


def test_fixture_row_values(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    (page,) = walk(client, headers, 20)

    (item,) = page["items"]
    assert item["id"] == str(imported.id)
    assert item["name"] == NAME
    assert item["card_name"] == "Cartão Exemplo"
    assert item["card_last4"] == "0000"
    assert item["status"] == "ready"
    assert item["failure_code"] is None
    assert item["failure_message"] is None
    assert item["total"] == "11906.35"
    assert item["transaction_count"] == 17
    assert item["pending_review_count"] == 2
    assert item["created_at"].endswith("Z")


def test_failed_status_and_reason_are_listed(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    with Session(engine) as session:
        set_status(session, imported.id, "failed", "extraction_timeout")

    (item,) = walk(client, headers, 20)[0]["items"]

    assert item["status"] == "failed"
    assert item["failure_code"] == "extraction_timeout"
    assert item["failure_message"] == "a leitura demorou demais"


def test_pending_review_follows_reviewed(client, engine):
    user_id, headers = person(client)
    import_for(engine, user_id, {"name": NAME, **extract()})

    (item,) = walk(client, headers, 20)[0]["items"]
    assert item["pending_review_count"] == 2
    with Session(engine) as session:
        line = session.scalars(
            select(Transaction).where(Transaction.description == "Software Gestão Teste")
        ).one()
        line.reviewed = True
        session.commit()

    (item,) = walk(client, headers, 20)[0]["items"]
    assert item["pending_review_count"] == 1


def test_empty_and_null_total_statements(client, engine):
    user_id, headers = person(client)
    with Session(engine) as session:
        session.add(Statement(user_id=uuid.UUID(user_id), name="Fatura Sem Total Exemplo"))
        session.commit()

    (item,) = walk(client, headers, 20)[0]["items"]

    assert item["total"] is None
    assert item["transaction_count"] == 0
    assert item["pending_review_count"] == 0


def test_one_statement_per_page(client, engine):
    user_id, headers = person(client)
    add_statements(engine, user_id, 20, lines=3)
    for limit in (1, 20, 100):
        responses = []
        statements = []

        def listener(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", listener)
        try:
            responses.append(client.get(f"/api/statements?limit={limit}", headers=headers))
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        assert responses[0].status_code == 200
        assert len(statements) == 2, limit


def test_other_users_rows_never_leak(client, engine):
    owner_id, owner_headers = person(client)
    other_id, other_headers = person(client, sub="sub-outro", email="outra@exemplo.com")
    _, empty_headers = person(client, sub="sub-vazio", email="vazio@exemplo.com")
    owner_ids = add_statements(engine, owner_id, 3)
    other_ids = add_statements(engine, other_id, 2, start=BASE + timedelta(days=1))

    owner_pages = walk(client, owner_headers, 1)
    assert ids_of(owner_pages) == list(reversed(owner_ids))

    cursor = owner_pages[0]["next_cursor"]
    borrowed = client.get(
        f"/api/statements?limit=20&cursor={cursor}", headers=other_headers
    ).json()
    assert set(ids_of([borrowed])) <= set(other_ids)
    assert not set(ids_of([borrowed])) & set(owner_ids)

    assert client.get("/api/statements", headers=empty_headers).json() == {
        "items": [],
        "next_cursor": None,
    }


def test_empty_list_is_200(client):
    _, headers = person(client)

    response = client.get("/api/statements", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_new_statement_does_not_shift_pages(client, engine):
    user_id, headers = person(client)
    ids = add_statements(engine, user_id, 5)
    first = client.get("/api/statements?limit=2", headers=headers).json()

    add_statements(engine, user_id, 1, start=BASE + timedelta(days=30))
    second = client.get(
        f"/api/statements?limit=2&cursor={first['next_cursor']}", headers=headers
    ).json()

    assert ids_of([second]) == list(reversed(ids))[2:4]


def test_app_role_lists_statements(client, engine):
    user_id, headers = person(client)
    add_statements(engine, user_id, 2, lines=1)

    response = client.get("/api/statements", headers=headers)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
