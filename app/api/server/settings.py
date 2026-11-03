from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
TLS_MODES = frozenset({"require", "verify-ca", "verify-full"})


def validate_database_url(raw: str, name: str) -> None:
    """Check a Postgres URL (BE-26). The messages name the variable and never
    include the value. Shared with the migration environment (BE-31)."""
    try:
        url = make_url(raw)
    except ArgumentError:
        raise ValueError(f"{name} is not a valid database URL") from None
    if url.drivername != "postgresql+psycopg":
        raise ValueError(f"{name} must use postgresql+psycopg://")
    if not url.host or not url.database:
        raise ValueError(f"{name} needs a host and a database name")
    if url.host not in LOOPBACK_HOSTS and url.query.get("sslmode") not in TLS_MODES:
        raise ValueError(
            f"{name} needs sslmode=require (or verify-ca or verify-full) for a "
            "host that is not loopback"
        )


class Settings(BaseSettings):
    """Portal settings, read from PORTAL_* environment variables.

    Each field has an explicit alias so a validation error names the
    variable (PORTAL_ENV), not the field. Secret fields added later use
    SecretStr.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    env: Literal["dev", "prod"] = Field("prod", alias="PORTAL_ENV")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        "INFO", alias="PORTAL_LOG_LEVEL"
    )
    # Cloudflare Access (BE-23). Neither is a secret. Both unset is allowed:
    # every protected route then answers 503 and /healthz stays up.
    access_team_domain: str | None = Field(
        None,
        alias="PORTAL_ACCESS_TEAM_DOMAIN",
        pattern=r"^[a-z0-9-]+\.cloudflareaccess\.com$",
    )
    access_aud: str | None = Field(
        None, alias="PORTAL_ACCESS_AUD", pattern=r"^[0-9a-f]{64}$"
    )

    # Postgres (BE-26): postgresql+psycopg://USER@HOST:PORT/DATABASE.
    # The error messages never include the value.
    database_url: SecretStr | None = Field(None, alias="PORTAL_DATABASE_URL")

    @field_validator("access_team_domain", "access_aud", "database_url", mode="before")
    @classmethod
    def blank_is_unset(cls, value: object) -> object:
        # A copied .env.example has these variables with no value.
        return None if value == "" else value

    @field_validator("database_url", mode="after")
    @classmethod
    def database_url_is_valid(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            validate_database_url(value.get_secret_value(), "PORTAL_DATABASE_URL")
        return value

    @model_validator(mode="after")
    def dev_uses_a_local_database(self) -> "Settings":
        if self.env == "dev" and self.database_url is not None:
            host = make_url(self.database_url.get_secret_value()).host
            if host not in LOOPBACK_HOSTS:
                raise ValueError(
                    "PORTAL_DATABASE_URL must point to this machine when "
                    "PORTAL_ENV=dev"
                )
        return self

    @model_validator(mode="after")
    def access_settings_go_together(self) -> "Settings":
        if (self.access_team_domain is None) != (self.access_aud is None):
            missing = (
                "PORTAL_ACCESS_AUD"
                if self.access_aud is None
                else "PORTAL_ACCESS_TEAM_DOMAIN"
            )
            raise ValueError(
                f"{missing} is required when the other Access setting is set"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
