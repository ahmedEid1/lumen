"""Application settings sourced from environment variables.

Read once at startup. Use the cached `get_settings()` everywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

    # ---------- BYOK envelope-encryption KEK (S7-pre / ADR-0027 §2) ----------
    # Versioned server master keys (KEK) that wrap each credential's
    # per-secret DEK. The map is ``{version:int -> base64(32-byte key)}``
    # and ``byok_master_key_version`` selects the *active* version used to
    # wrap new secrets; older versions are retained so already-stored
    # blobs (which carry their wrapping version in the header) keep
    # decrypting through a rotation (FR-BYOK-10/11/12, R-S2/R-S3).
    #
    # Accept either real JSON (``BYOK_MASTER_KEYS={"1":"<b64>"}``) or the
    # pydantic-settings default-empty case. When the map is empty AND
    # ``ENV != production`` the crypto module falls back to a clearly
    # dev-only KEK derived from ``secret_key`` (mirrors badges_keys.py).
    # In production an empty/derived KEK is a hard refusal — see
    # ``app.core.secrets_crypto`` + the boot guard in ``prod_guards.py``.
    byok_master_keys: dict[int, SecretStr] = Field(default_factory=dict)
    byok_master_key_version: int = 1

    # ---------- Capability flags (S7-pre / ADR-0025 §D2, R-CAP) ----------
    # ``ingest_url_enabled`` gates the URL-import capability. It stays
    # CLOSED (admin-only AND this flag) until the SSRF-hardening ADR lands
    # (R-M12, FR-SEC-02, charter decision 7) — the collapse to two roles
    # does NOT auto-open it. ``mcp_authoring_enabled`` replaces the old
    # is_instructor MCP gate: authoring is available to every active user
    # by default (FR-RBAC-08, FR-ADMIN-06).
    ingest_url_enabled: bool = False
    mcp_authoring_enabled: bool = True

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
    # Optional embedding-specific overrides. Lets an operator point the
    # embedding provider at a different OpenAI-compatible endpoint
    # (e.g. Cloudflare Workers AI's ``/accounts/<id>/ai/v1``) while
    # keeping the LLM call on a different one (Groq's chat-only API).
    # Falls back to ``openai_api_key`` / ``openai_api_base`` when unset.
    embedding_openai_api_key: SecretStr | None = None
    embedding_openai_api_base: str | None = None

    # ---------- RAG retrieval ACL + index freshness (ADR-0029 / PR-22) ----------
    # Cross-course HNSW ``ef_search`` (D5.2 / PR-4): on the cross-catalog path
    # the ACL clause can discard most private candidates before reaching
    # ``top_k`` (the "filtered-out recall" problem), so we widen the search
    # frontier there. Per-course retrieval keeps the pgvector default.
    rag_hnsw_ef_search_catalog: int = 100
    # Inline-index fallback bound (R-U2′ / D8): when a viewable course has live
    # lessons but zero chunks, the tutor triggers inline top-N indexing within
    # this staleness window so it never permanently refuses (FR-EMBED-02).
    index_max_staleness_s: int = 60
    index_inline_top_n: int = 5
    index_inline_timeout_s: int = 8

    # ---------- LLM (Phase E1 RAG tutor + E2 authoring assistant) ----------
    # Provider selector for ``app.services.llm`` — drives both the
    # RAG tutor (Phase E1) and the AI-assisted authoring service
    # (Phase E2). ``noop`` returns deterministic canned text for
    # tests so every CI run that touches an LLM path stays
    # network-free. Operators flip the provider via ``LLM_PROVIDER``;
    # ``LLM_MODEL`` overrides the per-provider default model id.
    llm_provider: Literal["anthropic", "openai", "mistral", "noop"] = "anthropic"
    llm_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_api_base: str | None = None
    llm_max_tokens: int = 1024

    # L41 — Mistral provider for the L25/L36 eval baseline + as a
    # second free-tier streaming option alongside Groq. Mistral's
    # Chat Completions API is OpenAI-compatible at this base URL —
    # the MistralProvider class wraps OpenAIProvider config so
    # callers just pick `LLM_PROVIDER=mistral` and the right
    # base+key+default-model resolves automatically.
    mistral_api_key: SecretStr | None = None
    mistral_api_base: str = "https://api.mistral.ai/v1"
    mistral_model: str = "mistral-small-latest"

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

    # ---------- BYOK (S5 / ADR-0027) ----------
    # Master gate. Ships OFF: the data model + code can deploy inert and be
    # enabled only after the KEK is confirmed present on every API + worker
    # process fleet-wide (R-S2/R-S3, boot guard in prod_guards). Mirrors the
    # feature_tutor_streaming env-backed pattern. When OFF: credential
    # write/resolve paths are inert and resolution is always platform.
    feature_byok_enabled: bool = False

    # Allow storing/validating a real BYOK key under a *derived* (dev-only)
    # KEK. Dev/test escape hatch — never set true in production (a derived
    # KEK there is a hard boot refusal anyway).
    byok_allow_derived_kek: bool = False

    # ---------- Non-dollar request/job quotas (DR-11/16, R-M7'/R-G1) ----------
    # Pre-dispatch DB COUNT(*) of llm_calls per user per window, independent
    # of dollars — this is what closes the $0-BYOK bypass (a free-priced BYOK
    # model still counts). Over-limit → status="quota_exceeded" row + a
    # RateLimitError, provider NOT invoked. Defaults are runaway-loop
    # trip-wires, generous for normal use.
    llm_user_request_quota_24h: int = 500
    llm_user_request_quota_1h: int = 120
    # BYOK users get higher request ceilings (they pay their own provider),
    # but keep the same concurrency/retry/timeout caps. The resolver picks
    # the window limits by billing_mode.
    byok_requests_24h: int = 2000
    byok_tokens_24h: int = 5_000_000  # post-dispatch dimension; informational here
    platform_requests_24h: int = 500
    # Redis concurrency lease (best-effort; Redis-down → fail-open, the DB
    # COUNT is the hard guard). TTL = provider timeout + buffer so a crashed
    # process's slot auto-expires.
    llm_max_concurrent: int = 4
    llm_max_retries: int = 2
    llm_provider_timeout_s: int = 60

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

    # ---------- Runtime feature flags (L20.5) ----------
    # Flags exposed via ``GET /api/v1/runtime-flags`` so the frontend
    # can branch behaviour without a redeploy. L21-Sec adds a Redis-
    # backed override layer; L20.5 ships only the wire shape (defaults
    # from this Settings object). New flags should default OFF so a
    # deploy that lands the code is observable but inert until an
    # operator opts in.
    #
    # ``feature_tutor_streaming`` — gates the SSE streaming endpoint
    # added in L21a + the streaming-renderer added in L21b. OFF until
    # L21b's flag-flip PR; until then the existing non-streaming POST
    # /tutor/conversations/{id}/messages path stays canonical.
    feature_tutor_streaming: bool = False

    # ``feature_private_publish_enabled`` (DR-13/DR-22 / S2.11) — gates the
    # visibility WRITE axis (the /share, /unshare, /resubmit endpoints). The
    # authorizer + columns ship first (backfilled → behaviour identical); this
    # flag flips to true only AFTER the authorizer-bearing image is fleet-
    # confirmed and the grep-guard is green (R-S8′ step 4). While OFF, the
    # sharing endpoints 404 — so no non-default visibility can be written and
    # there is no leak window. Env: FEATURE_PRIVATE_PUBLISH_ENABLED.
    feature_private_publish_enabled: bool = False

    # ---------- S6.3 — Course-report brigading controls (DR-20) ----------
    # Reporter eligibility: an account must be at least this many days old
    # (AND email-verified) to file a course report. Layered on top of the
    # per-user ≤10/h @limiter cap, this is the anti-brigading control — a
    # throwaway account can't be spun up to mass-report a course.
    report_min_account_age_days: int = 3
    # Per-course brigading cap: at most this many reports may be filed against a
    # single course within the rolling window before further reports are 429'd
    # (course.report_rate_limited). Distinct from the per-user @limiter cap.
    report_per_course_window_max: int = 5
    # The rolling window (hours) the per-course cap counts over.
    report_per_course_window_hours: int = 24
    # R-S11 accumulation threshold: when this many OPEN reports accumulate on a
    # course, an APPROVED course is requeued to pending_review for admin
    # confirmation (NEVER auto-delisted); a never-approved (none/pending) course
    # may auto-requeue to pending_review. The admin confirms the actual action.
    report_requeue_threshold: int = 3

    # ---------- L33 — Tutor cost caps & concurrency ----------
    # Per-turn estimate the POST handler reserves up-front. The
    # real cost gets reconciled on turn_complete (reconcile_cost
    # adjusts the bucket by `actual - estimate`). A conservative
    # estimate makes the demo "fail fast" for runaway users; too
    # low an estimate burns budget before the cap kicks in.
    # Default $0.005 = 5_000 microcents — covers a typical
    # Llama-3.3 70B Groq turn (~300 output tokens at $0.79/1M
    # output = ~$0.00024) with 20× headroom for outlier turns.
    tutor_estimate_microcents: int = 5_000

    # Per-user rolling-24h cap in microcents. $0.50 = 500_000.
    # ~100 typical turns/day before the user-cap kicks in.
    tutor_cap_user_microcents: int = 500_000

    # Per-IP rolling-24h cap. $2.00 = 2_000_000. Catches abuse
    # where one IP cycles many anonymous-shaped accounts.
    tutor_cap_ip_microcents: int = 2_000_000

    # Global rolling-24h cap. $20.00 = 20_000_000. The demo's
    # hard daily ceiling — exceeding it shuts the streaming
    # endpoint off until the bucket TTL expires.
    tutor_cap_global_microcents: int = 20_000_000

    # Max concurrent streaming turns per user. Beyond this the
    # POST returns 429 tutor.too_many_concurrent.
    tutor_max_concurrent: int = 3

    # ---------- L21-Sec deploy cutoff (Codex rescue) ----------
    # When the boot-hook backstop runs the email-verify grandfather
    # query, it must ONLY backfill rows whose ``created_at`` is older
    # than this timestamp. Without a cutoff, every API restart silently
    # grandfathers any user who registered after the L21-Sec deploy
    # and hasn't yet clicked their verification email — defeating the
    # whole point of the email-verification gate.
    #
    # The default value below is the L21-Sec migration timestamp
    # (UTC). Operators can override via `L21SEC_DEPLOY_TIMESTAMP` if
    # they need a different cutoff for a redeploy that ships
    # additional pre-existing users.
    l21sec_deploy_timestamp: datetime = datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC)

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
            problems.append(
                "WEB_BASE_URL is still the localhost default — emails would link to a dev host"
            )
        if "localhost" in str(self.badges_issuer_url):
            problems.append(
                "BADGES_ISSUER_URL is still the localhost default — issued OB3"
                " credentials would resolve to a dev host and fail external verification"
            )
        if problems:
            raise RuntimeError("Refusing to start: " + "; ".join(problems) + ". Update your .env.")

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
