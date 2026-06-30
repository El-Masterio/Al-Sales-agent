"""
app/core/config.py
==================
Single source of truth for all application configuration.
Loaded once at startup via module-level `settings` singleton.
All values are read from environment variables (or .env file).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    Field,
    PostgresDsn,
    RedisDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (two levels up from this file)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Application settings — sourced from environment variables.
    Nested sections are logical groupings; all vars live at the top level in .env.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_NAME: str = "AI Sales Agent"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = False
    APP_LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    SECRET_KEY: str = Field(min_length=32)
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @computed_field  # type: ignore[misc]
    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn
    DATABASE_SYNC_URL: str                          # for Alembic (psycopg2)
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 3600
    DATABASE_ECHO: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def database_url_str(self) -> str:
        return str(self.DATABASE_URL)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn
    REDIS_CELERY_BROKER: str
    REDIS_CELERY_BACKEND: str
    REDIS_CACHE_DB: int = 3
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5

    @computed_field  # type: ignore[misc]
    @property
    def redis_url_str(self) -> str:
        return str(self.REDIS_URL)

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str
    OPENAI_ORG_ID: str | None = None
    OPENAI_DEFAULT_MODEL: str = "gpt-4.1"
    OPENAI_FAST_MODEL: str = "gpt-4.1-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_MAX_RETRIES: int = 3
    OPENAI_TIMEOUT: int = 60
    OPENAI_MAX_TOKENS: int = 4096

    # ── Anthropic ─────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_DEFAULT_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_MAX_TOKENS: int = 4096

    # ── Google Gemini ─────────────────────────────────────────────────────────
    GOOGLE_AI_API_KEY: str | None = None
    GEMINI_DEFAULT_MODEL: str = "gemini-1.5-pro"

    # ── LLM Router ────────────────────────────────────────────────────────────
    LLM_PRIMARY_PROVIDER: Literal["openai", "anthropic", "google"] = "openai"
    LLM_FALLBACK_PROVIDER: Literal["openai", "anthropic", "google"] = "anthropic"
    LLM_TEMPERATURE: float = Field(default=0.7, ge=0.0, le=2.0)
    LLM_RESEARCH_TEMPERATURE: float = Field(default=0.2, ge=0.0, le=2.0)
    LLM_CREATIVE_TEMPERATURE: float = Field(default=0.9, ge=0.0, le=2.0)

    # ── Email — SendGrid ──────────────────────────────────────────────────────
    SENDGRID_API_KEY: str | None = None
    SENDGRID_WEBHOOK_KEY: str | None = None
    SENDGRID_TRACKING_DOMAIN: str | None = None

    # ── Email — AWS SES ───────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str = "us-east-1"
    SES_CONFIGURATION_SET: str = "sales-agent-tracking"
    SES_FROM_EMAIL: EmailStr | None = None

    # ── Email — SMTP ──────────────────────────────────────────────────────────
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False

    # ── Email Tracking ────────────────────────────────────────────────────────
    EMAIL_TRACKING_BASE_URL: AnyHttpUrl | None = None
    EMAIL_OPEN_PIXEL_PATH: str = "/t/{tracking_id}/open.png"
    EMAIL_CLICK_REDIRECT_PATH: str = "/t/{tracking_id}/click"
    EMAIL_DAILY_SEND_LIMIT: int = 500
    EMAIL_HOURLY_SEND_LIMIT: int = 50

    @computed_field  # type: ignore[misc]
    @property
    def email_tracking_base_url_str(self) -> str | None:
        if self.EMAIL_TRACKING_BASE_URL:
            return str(self.EMAIL_TRACKING_BASE_URL).rstrip("/")
        return None

    # ── Google Calendar ───────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: AnyHttpUrl | None = None
    GOOGLE_SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar"]

    @field_validator("GOOGLE_SCOPES", mode="before")
    @classmethod
    def parse_scopes(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",")]
        return v

    # ── Lead Enrichment ───────────────────────────────────────────────────────
    HUNTER_API_KEY: str | None = None
    CLEARBIT_API_KEY: str | None = None
    CRUNCHBASE_API_KEY: str | None = None
    APOLLO_API_KEY: str | None = None

    # ── Web Scraping ──────────────────────────────────────────────────────────
    SCRAPER_PROXY_URL: str | None = None
    SCRAPER_TIMEOUT: int = 30
    SCRAPER_MAX_RETRIES: int = 3
    SCRAPER_RATE_LIMIT_RPS: float = 2.0
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_SLOW_MO: int = 0

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_TASK_SOFT_TIME_LIMIT: int = 300
    CELERY_TASK_TIME_LIMIT: int = 600
    CELERY_MAX_RETRIES: int = 3
    CELERY_RETRY_BACKOFF: int = 60

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"
    RATE_LIMIT_EMAIL_SEND: str = "50/hour"

    # ── Campaign Defaults ─────────────────────────────────────────────────────
    DEFAULT_FOLLOW_UP_DAYS: list[int] = [3, 7, 14]
    DEFAULT_MAX_ATTEMPTS: int = 4
    DEFAULT_EMAIL_PROVIDER: Literal["sendgrid", "ses", "smtp"] = "sendgrid"
    DEFAULT_LLM_MODEL: str = "gpt-4.1"

    @field_validator("DEFAULT_FOLLOW_UP_DAYS", mode="before")
    @classmethod
    def parse_follow_up_days(cls, v: str | list[int]) -> list[int]:
        if isinstance(v, str):
            return [int(d.strip()) for d in v.split(",")]
        return v

    # ── Observability ─────────────────────────────────────────────────────────
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1
    SENTRY_ENVIRONMENT: str = "development"
    PROMETHEUS_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    # ── Security ──────────────────────────────────────────────────────────────
    ENCRYPTION_KEY: str = Field(min_length=32)
    WEBHOOK_SECRET: str | None = None
    CORS_ALLOW_CREDENTIALS: bool = True
    TRUSTED_HOSTS: list[str] = ["localhost"]
    API_KEY_HEADER: str = "X-API-Key"

    @field_validator("TRUSTED_HOSTS", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [h.strip() for h in v.split(",")]
        return v

    # ── Frontend ──────────────────────────────────────────────────────────────
    FRONTEND_URL: AnyHttpUrl = "http://localhost:3000"  # type: ignore[assignment]
    NEXT_PUBLIC_API_URL: AnyHttpUrl = "http://localhost:8000/api/v1"  # type: ignore[assignment]

    @computed_field  # type: ignore[misc]
    @property
    def frontend_url_str(self) -> str:
        return str(self.FRONTEND_URL).rstrip("/")

    # ── Feature Flags ─────────────────────────────────────────────────────────
    FEATURE_AUTO_RESEARCH: bool = True
    FEATURE_AUTO_OUTREACH: bool = True
    FEATURE_AUTO_FOLLOWUP: bool = True
    FEATURE_REPLY_CLASSIFICATION: bool = True
    FEATURE_AUTO_BOOKING: bool = True
    FEATURE_AI_MEMORY: bool = True
    FEATURE_LINKEDIN_SCRAPING: bool = False

    # ── Cross-field validation ─────────────────────────────────────────────────
    @model_validator(mode="after")
    def validate_email_provider(self) -> "Settings":
        provider = self.DEFAULT_EMAIL_PROVIDER
        if provider == "sendgrid" and not self.SENDGRID_API_KEY:
            raise ValueError("SENDGRID_API_KEY required when DEFAULT_EMAIL_PROVIDER=sendgrid")
        if provider == "ses" and not (self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY):
            raise ValueError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY required when "
                "DEFAULT_EMAIL_PROVIDER=ses"
            )
        if provider == "smtp" and not (self.SMTP_HOST and self.SMTP_USERNAME):
            raise ValueError(
                "SMTP_HOST and SMTP_USERNAME required when DEFAULT_EMAIL_PROVIDER=smtp"
            )
        return self

    @model_validator(mode="after")
    def validate_llm_provider(self) -> "Settings":
        provider = self.LLM_PRIMARY_PROVIDER
        if provider == "anthropic" and not self.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY required when LLM_PRIMARY_PROVIDER=anthropic")
        if provider == "google" and not self.GOOGLE_AI_API_KEY:
            raise ValueError("GOOGLE_AI_API_KEY required when LLM_PRIMARY_PROVIDER=google")
        return self

    # ── Helper properties ─────────────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def api_prefix(self) -> str:
        return "/api/v1"

    @computed_field  # type: ignore[misc]
    @property
    def docs_url(self) -> str | None:
        return "/docs" if not self.is_production else None

    @computed_field  # type: ignore[misc]
    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if not self.is_production else None

    @computed_field  # type: ignore[misc]
    @property
    def openapi_url(self) -> str | None:
        return "/openapi.json" if not self.is_production else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return cached Settings singleton.
    Use this function everywhere instead of importing `settings` directly
    so tests can override via `get_settings.cache_clear()` + monkeypatch.
    """
    return Settings()  # type: ignore[call-arg]


# Module-level singleton for convenience imports:
#   from app.core.config import settings
settings: Settings = get_settings()
