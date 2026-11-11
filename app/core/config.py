"""Application settings.

Every value comes from environment variables (or the .env file). Nothing is hardcoded here:
if a required variable is missing, the app fails fast at startup with a clear validation error.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str
    LOG_LEVEL: str

    # Database (sync SQLAlchemy + psycopg v3): postgresql+psycopg://user:pass@host:port/dbname
    DATABASE_URL: str

    # JWT
    JWT_SECRET_KEY: SecretStr
    JWT_ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(gt=0)

    # First admin, seeded at startup only when the users table is empty
    FIRST_ADMIN_EMAIL: str
    FIRST_ADMIN_PASSWORD: SecretStr

    # DNS discovery timeout per record type (seconds)
    DNS_TIMEOUT_SECONDS: float = Field(gt=0)

    # Redis / Celery. Broker and backend may be left empty to reuse REDIS_URL.
    REDIS_URL: str
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # Stale-scan sweeper thresholds (minutes)
    STALE_PENDING_MINUTES: int = Field(gt=0)
    STALE_RUNNING_MINUTES: int = Field(gt=0)

    @model_validator(mode="after")
    def _default_celery_urls(self) -> "Settings":
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
