from dataclasses import dataclass

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text


@dataclass(frozen=True)
class DatabaseInfo:
    role: str
    major_version: int


def build_engine(url: SecretStr) -> Engine:
    """Build the engine. It is lazy: nothing connects until first use."""
    return create_engine(
        url.get_secret_value(),
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
        # SQL text and parameters can hold transaction data (BE-21).
        echo=False,
        connect_args={
            # No server-side prepared statements: a transaction-mode pooler
            # breaks them.
            "prepare_threshold": None,
            "connect_timeout": 5,
            "application_name": "odiservices-api",
        },
    )


def check_database(engine: Engine) -> DatabaseInfo:
    with engine.connect() as connection:
        role, version_num = connection.execute(
            text("select current_user, current_setting('server_version_num')")
        ).one()
    return DatabaseInfo(role=role, major_version=int(version_num) // 10000)
