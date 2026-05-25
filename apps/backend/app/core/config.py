"""Application settings sourced from environment variables.

Read once at startup. Use the cached `get_settings()` everywhere.
"""

from __future__ import annotations

from decimal import Decimal
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
    api_host: str = "0.0.0.0"  # noqa: S104  intentional, bind in container
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

    # ---------- Open Badges 3.0 / W3C VC (Phase E5) ----------
    # ``badges_issuer_url`` is the platform's public identifier that
    # ends up baked into every issued credential's ``issuer.id``.
    # Per OB3 §8.1 verifiers expect it to dereference to a Profile
    # document (today the Lumen domain root suffices; once we migrate
    # to did:web the issuer ID will switch to ``did:web:<domain>``).
    # ``badges_signing_key`` is the Ed25519 private key in PEM form.
    # When unset (typical in dev/test) :mod:`app.core.badges_keys`
    # falls back to a key deterministically derived from
    # ``secret_key`` so a fresh ``docker compose up`` can issue and
    # verify credentials end-to-end without any extra setup. The
    # production guard refuses to boot if the dev secret leaks
    # through; see :meth:`assert_production_ready`.
    badges_issuer_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    badges_signing_key: SecretStr = SecretStr("")

    # ---------- Embeddings (Phase E0) ----------
    # Provider for ``app.services.embeddings`` — selects which concrete
    # ``EmbeddingProvider`` implementation backs the ingest + retrieval
    # pipeline. ``local`` uses ``sentence-transformers/all-MiniLM-L6-v2``
    # (CPU-friendly, fully self-hostable, 384-dim). ``openai`` calls
    # ``text-embedding-3-small`` with ``dimensions=384`` so the column
    # shape stays constant across providers. ``noop`` returns zero
    # vectors with a deterministic seed — for tests only.
    embedding_provider: Literal["local", "openai", "noop"] = "local"
    embedding_model_local: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_openai: str = "text-embedding-3-small"
    openai_api_key: SecretStr | None = None
    openai_api_base: str = "https://api.openai.com/v1"

    # ---------- LLM (Phase E1 RAG tutor + E2 authoring assistant) ----------
    # Provider selector for ``app.services.llm`` — drives both the
    # RAG tutor (Phase E1) and the AI-assisted authoring service
    # (Phase E2). ``noop`` returns deterministic canned text for
    # tests so every CI run that touches an LLM path stays
    # network-free. Operators flip the provider via ``LLM_PROVIDER``;
    # ``LLM_MODEL`` overrides the per-provider default model id.
    llm_provider: Literal["anthropic", "openai", "noop"] = "anthropic"
    llm_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_api_base: str | None = None
    llm_max_tokens: int = 1024

    # ---------- LLM cost tracking + budget guard (Phase H1) ----------
    # Every LLM round-trip through ``app.services.llm_call_log`` is
    # recorded in the ``llm_calls`` table when this flag is on. The
    # meter is essentially free (one INSERT per call, ~µs), so it's
    # ON by default — the flag exists so operators can disable it for
    # synthetic-load benchmarks or while debugging a migration.
    llm_cost_tracking_enabled: bool = True
    # Per-user rolling-24h spend cap in USD. The wrapper sums
    # ``cost_usd`` for the caller over the last day; once the sum
    # exceeds this threshold the next call short-circuits with
    # ``BudgetExceededError`` (still persisted as a row with
    # ``status="budget_exceeded"`` so the admin surface sees the
    # spike). Default ``$1.00`` is deliberately tiny — Lumen runs on
    # Groq's free tier in the public demo, where token cost is
    # nominal; the guard is really a runaway-loop trip-wire, not a
    # billing meter. Bump in ``.env`` for power users / production.
    llm_user_budget_24h_usd: Decimal = Decimal("1.00")

    # ---------- Content ingest (Phase E3) ----------
    # Optional Notion integration token. When unset, the Notion
    # extractor refuses with a clean 422 ("set NOTION_TOKEN") rather
    # than attempting to scrape Notion's HTML. Public Notion pages
    # *can* be served without auth, but the embedded ``__NEXT_DATA__``
    # JSON shape is brittle enough that we'd rather lean on the
    # supported integration API. YouTube + Google Docs paths don't
    # need any credentials — public videos expose transcripts to
    # ``youtube-transcript-api`` and "anyone with the link" Docs
    # expose a plaintext export.
    notion_token: SecretStr | None = None

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
        if "localhost" in str(self.badges_issuer_url):
            problems.append(
                "BADGES_ISSUER_URL is still the localhost default — issued OB3"
                " credentials would resolve to a dev host and fail external verification"
            )
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
