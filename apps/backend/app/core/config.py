"""Application settings sourced from environment variables.

Read once at startup. Use the cached `get_settings()` everywhere.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"
    test = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- App ----------
    env: Environment = Environment.development
    app_name: str = "Lumen"
    app_domain: str = "localhost"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    tz: str = "UTC"

    # ---------- API ----------
    api_host: str = "0.0.0.0"  # intentional, bind in container
    api_port: int = 8000
    api_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    # User-facing frontend origin — embedded in transactional emails
    # (password reset, email verification) so links resolve to the Next.js
    # app, not the FastAPI host where those routes don't exist.
    web_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ---------- Crypto ----------
    secret_key: SecretStr = SecretStr("change-me")
    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    password_reset_ttl_seconds: int = 1800

    # ---------- DB ----------
    database_url: str = "postgresql+asyncpg://lumen:lumen@db:5432/lumen"
    database_url_sync: str = "postgresql+psycopg://lumen:lumen@db:5432/lumen"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ---------- Redis ----------
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ---------- S3 / MinIO ----------
    s3_endpoint_url: str = "http://s3:9000"
    s3_public_base_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "lumen-assets"
    s3_access_key_id: str = "lumen"
    s3_secret_access_key: SecretStr = SecretStr("lumen-secret")
    s3_force_path_style: bool = True
    s3_presign_ttl_seconds: int = 900

    # ---------- Search ----------
    search_backend: Literal["meilisearch", "postgres"] = "meilisearch"
    meili_url: str = "http://search:7700"
    meili_master_key: SecretStr = SecretStr("lumen-search-key")
    meili_index_courses: str = "courses"

    # ---------- Email ----------
    smtp_host: str = "mail"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "Lumen <no-reply@lumen.test>"
    smtp_tls: bool = False

    # ---------- Observability ----------
    sentry_dsn: str = ""
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "lumen-api"
    prometheus_enabled: bool = True

    # ---------- Misc ----------
    seed_demo: bool = True
    rate_limit_anon_per_minute: int = 60
    rate_limit_auth_per_minute: int = 10
    rate_limit_user_per_minute: int = 240

    # ---------- HIBP (breach-list lookup) ----------
    # Opt-in because (a) it adds a ~200ms external call to register/reset
    # and (b) some deployments don't want any third-party callout. When
    # enabled, the password is k-anonymized (first 5 chars of its SHA-1
    # sent over the wire — never the full hash, never the password) and
    # rejected if HIBP reports any breaches. Network failures fail open
    # so an upstream outage can't lock users out.
    hibp_enabled: bool = False
    hibp_api_base: str = "https://api.pwnedpasswords.com"
    hibp_timeout_seconds: float = 2.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def assert_production_ready(self) -> None:
        """Raise if any production-sensitive config is still at a dev default.

        Called at startup when ``env=production``. Better to refuse to boot than
        to silently expose a fixed signing key.
        """
        if self.env != Environment.production:
            return
        problems: list[str] = []
        if self.secret_key.get_secret_value() in {"", "change-me"}:
            problems.append("SECRET_KEY is unset or still the dev default")
        if self.jwt_secret.get_secret_value() in {"", "change-me"}:
            problems.append("JWT_SECRET is unset or still the dev default")
        if self.s3_secret_access_key.get_secret_value() in {"", "lumen-secret"}:
            problems.append("S3_SECRET_ACCESS_KEY is still the dev default")
        if any("localhost" in o for o in self.cors_origins):
            problems.append("CORS_ORIGINS contains localhost in production")
        if "localhost" in str(self.web_base_url):
            problems.append("WEB_BASE_URL is still the localhost default — emails would link to a dev host")
        if problems:
            raise RuntimeError(
                "Refusing to start: " + "; ".join(problems) + ". Update your .env."
            )

    @property
    def is_prod(self) -> bool:
        return self.env == Environment.production

    @property
    def is_dev(self) -> bool:
        return self.env == Environment.development

    @property
    def is_test(self) -> bool:
        return self.env == Environment.test


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
