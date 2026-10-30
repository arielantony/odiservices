from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
