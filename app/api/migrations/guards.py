"""Rules the migration environment enforces before it connects (BE-31)."""

from collections.abc import Mapping

from sqlalchemy.engine import make_url

from server.settings import LOOPBACK_HOSTS, validate_database_url

VARIABLE = "PORTAL_MIGRATION_DATABASE_URL"


class MigrationGuardError(RuntimeError):
    """A rule was broken. The message never includes the URL."""


def migration_url(environ: Mapping[str, str]) -> str:
    url = environ.get(VARIABLE, "")
    if not url:
        raise MigrationGuardError(f"{VARIABLE} is not set")
    try:
        validate_database_url(url, VARIABLE)
    except ValueError as error:
        raise MigrationGuardError(str(error)) from None
    return url


def refuse_remote_downgrade(url: str) -> None:
    """Production moves forward only: a downgrade runs on this machine only."""
    if make_url(url).host not in LOOPBACK_HOSTS:
        raise MigrationGuardError(
            "a downgrade runs only against a database on this machine; "
            "production moves forward only"
        )


def next_revision_id(head: str | None) -> str:
    if not head:
        return "0001"
    if not head.isdigit():
        raise MigrationGuardError(
            f"the head revision {head!r} is not a number; ids here are 0001, 0002, ..."
        )
    return f"{int(head) + 1:04d}"
