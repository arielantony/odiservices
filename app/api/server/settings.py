from pydantic import BaseModel


class Settings(BaseModel):
    """Placeholder until BE-18 loads it from PORTAL_* environment variables."""

    env: str = "prod"
