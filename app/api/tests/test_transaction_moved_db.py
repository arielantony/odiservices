"""The moved_by_user flag against a real Postgres (BE-13). Run by make test-db;
the app connects as app_backend. The statement is imported through
import_statement (BE-05); moves go through PATCH (BE-11) and reads through GET
(BE-10). Line 8 is "Notebook Loja Fictícia", imported as INVESTIMENTO."""

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
    get,
    import_for,
    person,
)
from test_transaction_update_db import lines_of, line, patch

pytestmark = pytest.mark.db

MOVED_LINE = "Notebook Loja Fictícia"
DOUBTFUL_LINE = "Software Gestão Teste"


def stored_originals(migrated, statement_id) -> dict[int, tuple[str, str]]:
    """item_number -> (category_code, original_category_code), read as the owner."""
    with owner(migrated).connect() as connection:
        rows = connection.execute(
            text(
                "select item_number, category_code, original_category_code "
                "from portal.transactions where statement_id = :s"
            ),
            {"s": statement_id},
        ).all()
    return {number: (category, original) for number, category, original in rows}


def test_import_sets_original_to_the_imported_category(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})

    stored = stored_originals(migrated, imported.id)
    assert len(stored) == 17
    assert all(category == original for category, original in stored.values())
    lines = lines_of(client, imported.id, headers)
    assert len(lines) == 17
    assert all(item["moved_by_user"] is False for item in lines)


def test_move_sets_the_flag(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    target = line(client, imported.id, headers, MOVED_LINE)

    response = patch(client, imported.id, target["id"], {"category_code": "FORNECEDOR"}, headers)

    assert response.status_code == 200
    assert response.json()["category_code"] == "FORNECEDOR"
    assert response.json()["moved_by_user"] is True
    stored = stored_originals(migrated, imported.id)
    assert stored[8] == ("FORNECEDOR", "INVESTIMENTO")


def test_move_back_clears_the_flag(client, engine, migrated):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    target = line(client, imported.id, headers, MOVED_LINE)
    patch(client, imported.id, target["id"], {"category_code": "FORNECEDOR"}, headers)

    response = patch(client, imported.id, target["id"], {"category_code": "INVESTIMENTO"}, headers)

    assert response.status_code == 200
    assert response.json()["moved_by_user"] is False
    assert stored_originals(migrated, imported.id)[8] == ("INVESTIMENTO", "INVESTIMENTO")


def test_confirm_does_not_set_the_flag(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    doubt = line(client, imported.id, headers, DOUBTFUL_LINE)

    response = patch(client, imported.id, doubt["id"], {"reviewed": True}, headers)

    assert response.status_code == 200
    assert response.json()["reviewed"] is True
    assert response.json()["moved_by_user"] is False


def test_read_marks_only_the_moved_line(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    target = line(client, imported.id, headers, MOVED_LINE)
    patch(client, imported.id, target["id"], {"category_code": "FORNECEDOR"}, headers)

    lines = lines_of(client, imported.id, headers)

    flagged = [item["description"] for item in lines if item["moved_by_user"]]
    assert flagged == [MOVED_LINE]
    assert sum(1 for item in lines if item["moved_by_user"] is False) == 16


def test_move_then_undo_restores_the_import_state(client, engine):
    user_id, headers = person(client)
    imported = import_for(engine, user_id, {"name": NAME, **extract()})
    before = line(client, imported.id, headers, MOVED_LINE)

    patch(client, imported.id, before["id"], {"category_code": "FORNECEDOR"}, headers)
    undone = patch(client, imported.id, before["id"], {"category_code": "INVESTIMENTO"}, headers)

    assert undone.status_code == 200
    assert line(client, imported.id, headers, MOVED_LINE) == before
    assert before["moved_by_user"] is False
