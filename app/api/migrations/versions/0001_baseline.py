"""baseline: the portal schema and the app_backend role

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# A role used by the server: it reads and writes rows and cannot change the
# schema. It is created with no credential: the owner sets it with \password.
CREATE_ROLE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_backend') THEN
        CREATE ROLE app_backend LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$
"""

# Supabase's API roles exist there and not on a plain Postgres.
REVOKE_API_ROLES = """
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON SCHEMA portal FROM anon;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON SCHEMA portal FROM authenticated;
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS portal")
    op.execute(CREATE_ROLE)
    op.execute("REVOKE ALL ON SCHEMA portal FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA portal TO app_backend")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA portal "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA portal "
        "GRANT USAGE, SELECT ON SEQUENCES TO app_backend"
    )
    op.execute(REVOKE_API_ROLES)
    op.execute("ALTER ROLE app_backend SET statement_timeout = '15s'")
    op.execute(
        "ALTER ROLE app_backend SET idle_in_transaction_session_timeout = '30s'"
    )


def downgrade() -> None:
    # The schema stays: env.py creates it for Alembic's own version table, and
    # the role stays: it belongs to the whole server, not to one database.
    op.execute("ALTER ROLE app_backend RESET idle_in_transaction_session_timeout")
    op.execute("ALTER ROLE app_backend RESET statement_timeout")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA portal "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM app_backend"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA portal "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_backend"
    )
    op.execute("REVOKE USAGE ON SCHEMA portal FROM app_backend")
