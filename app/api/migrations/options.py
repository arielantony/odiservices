"""Autogenerate and version-table options shared by `env.py` and the drift test."""

from server.db.base import SCHEMA


def include_name(name, type_, parent_names):
    # Supabase owns other schemas (public, auth, storage, ...): leave them.
    # A model with no schema (name None) is left out too; the test
    # `test_every_model_is_in_the_portal_schema` keeps that from happening.
    if type_ == "schema":
        return name == SCHEMA
    return True


def base_options() -> dict:
    return dict(
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
    )
