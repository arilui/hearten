from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables (and a local .env file in development)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://hearten:hearten@localhost:5432/hearten"
    # In AWS, the connection string lives in SSM Parameter Store (encrypted), and
    # this names the parameter; the value is fetched once at startup.
    database_url_param: str | None = None
    # Comma-separated list of frontend origins allowed to call the API.
    allowed_origins: str = "http://localhost:3000"

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Accept connection strings exactly as Neon and other hosts give them."""
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


def read_ssm_parameter(name: str) -> str:
    import boto3  # available in the AWS Lambda runtime; not needed locally

    response = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.database_url_param:
        settings = Settings(database_url=read_ssm_parameter(settings.database_url_param))
    return settings
