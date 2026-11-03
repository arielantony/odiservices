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


# Commands that only move forward or read. Anything else (a downgrade, or a
# call that does not come from the CLI) is refused on a remote host.
REMOTE_COMMANDS = {"upgrade", "current", "heads", "history", "branches", "show", "check"}


def refuse_remote_unless_forward(url: str, command: str | None) -> None:
    """Production moves forward only. On a host that is not this machine, only a
    known forward or read-only command runs; an unknown one is refused."""
    if make_url(url).host in LOOPBACK_HOSTS or command in REMOTE_COMMANDS:
        return
    raise MigrationGuardError(
        "a downgrade runs only against a database on this machine; "
        "production moves forward only"
    )


def describe_target(url: str) -> str:
    """Host and database, for the line that says where a command runs. Never
    the user, the password or the query."""
    parsed = make_url(url)
    return f"{parsed.host}/{parsed.database}"


def next_revision_id(head: str | None) -> str:
    if not head:
        return "0001"
    if not head.isdigit():
        raise MigrationGuardError(
            f"the head revision {head!r} is not a number; ids here are 0001, 0002, ..."
        )
    return f"{int(head) + 1:04d}"
