"""Prove that the configured database answers: python -m server.db."""

import sys

from sqlalchemy import Engine

from server.db.engine import build_engine, check_database
from server.settings import Settings


def run(settings: Settings, engine: Engine | None = None) -> int:
    if settings.database_url is None:
        print("database not configured")
        return 1
    try:
        info = check_database(engine or build_engine(settings.database_url))
    except Exception as error:
        # The class only: a driver message can hold the host and the user.
        print(f"database unavailable: {type(error).__name__}")
        return 1
    print(f"database ok (role={info.role}, postgres={info.major_version})")
    return 0


if __name__ == "__main__":
    sys.exit(run(Settings()))
