from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("access_team_domain", "access_aud", mode="before")
    @classmethod
    def blank_is_unset(cls, value: object) -> object:
        # A copied .env.example has these variables with no value.
        return None if value == "" else value

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
