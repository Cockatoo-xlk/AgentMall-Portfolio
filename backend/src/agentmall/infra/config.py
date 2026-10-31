from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="AGENTMALL_", extra="ignore"
    )
    database_url: SecretStr
    test_database_url: SecretStr | None = None
    jwt_secret: SecretStr
    jwt_issuer: str = "agentmall"
    jwt_audience: str = "agentmall-api"
    jwt_minutes: int = Field(default=15, ge=1, le=15)
    mock_payment_result: Literal["SUCCEEDED", "DECLINED"] = "SUCCEEDED"
    storefront_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    db_schema: str = Field(default="public", pattern=r"^(public|test_[0-9a-f]{32})$")
    checkpoint_schema: str | None = Field(default=None, pattern=r"^cp_[0-9a-f]{32}$")

    @field_validator("database_url", "test_database_url")
    @classmethod
    def dedicated_postgres(cls, value):
        if value is None:
            return value
        url = make_url(value.get_secret_value())
        if (
            url.drivername != "postgresql+psycopg"
            or url.database not in {"agentmall", "agentmall_test"}
            or url.username != "agentmall"
            or url.query
        ):
            raise ValueError("Use the dedicated agentmall PostgreSQL databases without URL options")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def long_secret(cls, value):
        raw = value.get_secret_value()
        if len(raw) < 32 or raw.startswith("replace-with-"):
            raise ValueError("Generate a JWT secret of at least 32 characters")
        return value
