# ADR 0027: BYOK — Allowlisted Provider Registry, Envelope-Encrypted Per-User Credentials, Initiation-Locus Model Selection, Non-Dollar Quotas, and Redaction

## Status — Proposed

Supersedes the BYOK-with-user-`api_base` sketch in CHARTER §3 (v1). Implements charter decision 5 (v2) and REQUIREMENTS-RESOLUTIONS mandatory W2 ADR-3. Authoritative inputs: REQUIREMENTS-RESOLUTIONS.md (R1+R2+R3) over the spec on conflict. Targets work-stream **S5**.

## Context (forces + current code reality with file:line)

**What exists today (verified against source):**

- LLM provider selection is **global, per-call, zero-arg**: `get_provider()` reads `Settings.llm_provider` and builds one of `NoopProvider | OpenAIProvider | MistralProvider | AnthropicProvider` (`app/services/llm.py:478-514`). There is no `user_id` parameter and no per-user resolution.
- **Provider classes hold the raw key in cleartext** with no redaction: `AnthropicProvider.__init__` stores `self._api_key = api_key` (`llm.py:200`); `OpenAIProvider` likewise (`llm.py:312`); `MistralProvider` inherits it (`llm.py:460`). No `__repr__`/`__str__` guard exists → `repr(provider)` would print the key. This is the active leak charter §3 and FR-BYOK-23 call out.
- **`api_base` is a free-form constructor arg** wired straight into the vendor SDK `base_url` (`llm.py:211` Anthropic, `llm.py:323` OpenAI; streaming `llm_stream.py:181,219,297`). Settings expose `openai_api_base`, `anthropic_api_base`, `mistral_api_base` as plain strings (`config.py:128,147,157`). This is the SSRF/exfil surface — BYOK MUST NOT let a user set it.
- **The streaming path forks the global switch independently** of `get_provider()`: `stream_chat()` re-reads `settings.llm_provider` and dispatches `_stream_chat_noop/_openai/_anthropic/_openai_compat` reading `settings.*_api_key` directly (`llm_stream.py:93-119, 170-183, 290-298`). FR-BYOK-03: must share one resolver.
- **The streaming tutor runs in a Celery worker.** `run_turn` (`workers/tasks/tutor_streaming.py:59`) → `orchestrate_stream` (`tutor_orchestrator_stream.py:171`) → `stream_chat(messages)`. The worker holds `turn.user_id` (`tutor_streaming.py:97`). So BYOK for the primary tutor UX MUST reach a worker — this is the R-S1″ load-bearing fact (R-S1′ folded `app/db/base.make_worker_engine` + co-located host).
- **Non-streaming chat call sites all already pass `user_id`** into `call_logged`, and each builds the provider via zero-arg `get_provider()`: `tutor_orchestrator.py:654`, `authoring_orchestrator.py:484`, `learning_path.py:757`, `tutor_subagents/concept_explainer.py:110`, `tutor_subagents/quiz_generator.py` (around :146/:159). Threading a credential context is mechanical because the user id is already in scope.
- **Foreground vs background learning-path is the same service function.** `POST /me/learning-path` → `build_path` (`api/v1/learning_path.py:181`), `POST /me/learning-path/replan` → `replan_for_user` (`learning_path.py:271`) are user-triggered; the monthly beat `replan_paths_monthly` (`workers/tasks/learning_path.py:130`) calls the **same** `replan_for_user` (`workers/tasks/learning_path.py:70`). The locus must be decided by the **caller's initiation context**, not by the function — exactly R-S1″.
- **Authoring/goal-build is in-request.** `POST /ai/courses/draft` awaits `authoring_orchestrator.draft_course` (`api/v1/ai_authoring.py:328`), no `.delay()`.
- **The dollar guard is bypassed by $0 BYOK calls.** `call_logged` sums `LLMCall.cost_usd` over 24h and trips `BudgetExceededError` (`llm_call_log.py:227-259`); `compute_cost_usd` returns `Decimal("0.000000")` for unknown models (`llm_pricing.py:84`). A BYOK call on a model absent from `MODEL_PRICING` (`llm_pricing.py:52-56`) costs $0 in the guard → unlimited. This is the R-M7′ / FR-QUOTA-01 driver for **non-dollar** quotas.
- **Existing redaction is key-name-only**, not value-level: `logging.py:31 _redact` masks `event_dict` keys in `_REDACT_KEYS` (`logging.py:20-28`). It cannot catch a decrypted key that lands as a *value* in an arbitrary log field, exception arg, or trace payload. R-U3 needs a value-level sentinel filter across all sinks.
- **Boot guards exist on the API only.** `Settings.assert_production_ready()` (`config.py:264`) + `assert_production_safe` (`prod_guards.py:199`) run in the FastAPI lifespan (`main.py:262,268`). The Celery worker has **no** boot guard hook (`workers/celery_app.py` registers tasks + beat only). R-S1′(e)/R-S3 require the guard on **both**.
- **Envelope-crypto precedent:** `badges_keys.py` is Ed25519 *signing* (asymmetric), not symmetric encryption, and FR-BYOK-09 explicitly forbids reusing it. But its dev-fallback pattern (derive deterministic key from `secret_key` via domain-separated SHA-256: `badges_keys.py:67`) is the template for the dev KEK. `cryptography` is already a dependency.
- **Redis lease primitives exist:** `cost_scripts.check_concurrency` / `release_concurrency` (`core/cost_scripts.py:109,132`) implement TTL'd per-user slot counters via Lua. These are the model for the R-M7′ concurrency lease.
- **Model/migrations:** latest Alembic revision is `0029` (`alembic/versions/2026_07_28_0029-...py`); new migrations start at **0030**. IDs are 21-char nanoid via `IdMixin` (`db/base.py:46-47`). `User` has no per-user capability storage (`models/user.py`); R-CAP makes v1 capabilities pure functions over `(User + global config)`, suspension via `is_active` (`user.py:38`).
- **Admin cost surface:** `admin_llm_calls.py` reads `LLMCall` rows + sums `cost_usd` (`admin_llm_calls.py:170`); has no `billing_mode` notion (FR-BYOK-27/28).

**Forces:** (1) never decrypt a key outside the dispatch call; (2) the primary tutor is worker-executed so the KEK must live in the worker trust boundary too; (3) the dollar guard is structurally insufficient; (4) zero-downtime against a live prod fleet (API + worker co-located on the AWS t4g.small per the AWS-deployment memory); (5) SSRF closure by construction (no user URLs); (6) validate-endpoint must not become a key-testing oracle.

## Decision (the concrete chosen design)

### 1. Allowlisted provider registry (code, not user input) — `app/services/llm_providers.py`

A frozen in-code registry. The base URL is **never** user-supplied (closes SSRF at `llm.py:211,323`).

```python
@dataclass(frozen=True)
class ProviderSpec:
    key: str                       # "openai" | "anthropic" | "groq" | "mistral"
    display_name: str
    base_url: str                  # FIXED, server-owned
    transport: Literal["openai", "anthropic"]  # which Provider class
    models: tuple[str, ...]        # curated allowlist (R-G4)
    key_min_len: int
    key_max_len: int = 512
    validate_strategy: Literal["chat_min", "models_list"]

PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
  "openai":    ProviderSpec("openai","OpenAI","https://api.openai.com/v1","openai",
                            ("gpt-4o-mini","gpt-4o"), 20, validate_strategy="chat_min"),
  "anthropic": ProviderSpec("anthropic","Anthropic","https://api.anthropic.com","anthropic",
                            ("claude-sonnet-4-6","claude-haiku-4-5-20251001"), 20, validate_strategy="chat_min"),
  "groq":      ProviderSpec("groq","Groq","https://api.groq.com/openai/v1","openai",
                            ("llama-3.3-70b-versatile",), 20, validate_strategy="chat_min"),
  "mistral":   ProviderSpec("mistral","Mistral","https://api.mistral.ai/v1","openai",
                            ("mistral-small-latest",), 20, validate_strategy="chat_min"),
}
```

`groq` becomes a first-class registry entry (FR-BYOK-13). Registry maintenance is an admin/code task; W2 chooses **code constant** (not a DB table) as source of truth — versioned with the app, no admin CRUD surface in v1 (R-G4). Exposed read-only via `GET /api/v1/llm-providers` so the frontend never hard-codes the list (FR-BYOK-20).

### 2. Envelope encryption — `app/core/secrets_crypto.py` (NEW, do not reuse `badges_keys.py`)

Per credential: random 256-bit **DEK** → AES-256-GCM encrypt the API key under the DEK → wrap the DEK under the versioned server **KEK**.

```python
def encrypt_secret(plaintext: str) -> EncryptedSecret:
    dek = AESGCM.generate_key(bit_length=256)
    n1 = os.urandom(12); enc_key = n1 + AESGCM(dek).encrypt(n1, plaintext.encode(), None)
    kek_v, kek = _active_kek()                       # (version, 32-byte key)
    n2 = os.urandom(12); enc_data_key = n2 + AESGCM(kek).encrypt(n2, dek, None)
    return EncryptedSecret(enc_key=enc_key, enc_data_key=enc_data_key, key_version=kek_v)

def decrypt_secret(enc_key, enc_data_key, key_version) -> str:   # called ONLY in dispatch
    kek = _kek_for_version(key_version)
    dek = AESGCM(kek).decrypt(enc_data_key[:12], enc_data_key[12:], None)   # never logged
    return AESGCM(dek).decrypt(enc_key[:12], enc_key[12:], None).decode()

def key_fingerprint(plaintext: str) -> str:    # SHA-256 hex, for dedupe/idempotency (FR-BYOK-08)
    return hashlib.sha256(plaintext.encode()).hexdigest()

def last4(plaintext: str) -> str:
    return plaintext[-4:] if len(plaintext) >= 4 else "****"
```

**KEK source (FR-BYOK-10/11, R-S3):** `Settings.byok_master_keys: dict[int,SecretStr]` (version→base64 32-byte key) + `byok_master_key_version: int`. Dev/test fallback derives a clearly-ephemeral KEK `sha256(b"lumen.byok.kek.v1:" + secret_key)` (mirrors `badges_keys.py:67`), tagged `derived=True`; **never** used when `ENV=production`. Rotation (`rotate_byok_master_key`, FR-BYOK-12) unwraps each `enc_data_key` under version N and re-wraps under N+1 in batched transactions, **never** touching `enc_key`/plaintext; preconditions per R-S2 (all versions deployed fleet-wide before rotation; old version retained until done); emits `byok.master_key_rotated` (counts only). Runbook: `docs/runbooks/byok-key-rotation.md`.

### 3. Boot guard on API **and** worker (R-S3, R-S1′e/f)

`prod_guards.check_byok_master_key(settings, problems)`: append a hard problem when **any `user_llm_credentials` row exists** (or `ENV=production`) and the KEK is empty / derived-from-`secret_key` / `< 32` bytes — in **any** env, not just prod (R-S3). Wire into:
- API lifespan after `assert_production_safe` (`main.py:268`).
- A **new** Celery `worker_init` / `on_after_configure` signal handler in `workers/celery_app.py` that runs the same guard and aborts worker boot on failure.

The store/validate endpoint **refuses to persist a real key under a derived KEK** unless `BYOK_ALLOW_DERIVED_KEK=true` is explicitly opted in (dev only); real BYOK keys in non-prod are forbidden by policy.

### 4. Model-selection locus = **INITIATION, not execution** (R-S1″) — `app/services/byok.py`

A single dispatch module owns resolution + decryption-at-call-only.

```python
@dataclass(frozen=True)
class LLMContext:
    """Threaded from the *initiator*. Decides BYOK vs platform."""
    user_id: str | None            # acting user; None / SYSTEM_USER_ID => platform
    credential_id: str | None      # set by foreground resolver; carried in Celery payloads
    foreground: bool               # True => user-initiated; False => beat/system => platform

PLATFORM_CONTEXT = LLMContext(user_id=SYSTEM_USER_ID, credential_id=None, foreground=False)

async def resolve_context(db, *, user_id) -> LLMContext:
    """API-side: pick the user's active/enabled/not-invalid credential id (no decrypt)."""

async def build_provider(db, ctx: LLMContext) -> tuple[LLMProvider, str]:
    """Decrypt ONLY here. Returns (provider, billing_mode). Applies R-M11′ drift +
       R-S1″ platform fallback for background ctx."""
```

**Classification rule (settles every current + future feature):**

| Feature | Initiation | Model |
|---|---|---|
| Interactive tutor (`tutor_orchestrator.py:654`) | foreground (API) | **BYOK** |
| Streaming tutor (`tutor_streaming.py`→`orchestrate_stream`→`stream_chat`) | foreground (worker, credential_id in payload) | **BYOK** |
| Authoring / goal-build (`ai_authoring.py:328`, `authoring_orchestrator.py:484`) | foreground (API) | **BYOK** |
| Tutor subagents (`concept_explainer.py:110`, `quiz_generator.py`) | foreground (inherit parent ctx) | **BYOK** |
| Learning-path **build** (`learning_path.py:181`) + **manual replan** (`learning_path.py:271` via API) | foreground (API) | **BYOK** |
| **Monthly beat** replan (`workers/tasks/learning_path.py:130`) | background (no user in loop) | **platform** |
| Embeddings (`embeddings_ingest.py:156,201`, `workers/tasks/embeddings.py`) | platform-pinned | **platform** |
| Eval/judge/runner | operator | **platform** |

`replan_for_user(db, user_id, *, ctx: LLMContext = PLATFORM_CONTEXT)` — the API handler passes `resolve_context(...)`; the beat passes the default `PLATFORM_CONTEXT`. Same function, locus decided by caller. **Celery payloads carry `credential_id` only, never the key** (FR-BYOK-26); the worker re-resolves + decrypts from DB inside `build_provider`.

**Streaming integration (FR-BYOK-03):** `stream_chat(messages, *, ctx: LLMContext)` stops re-reading the global switch. It calls `build_provider(db, ctx)` to get `(provider_spec, key)` and dispatches `_stream_chat_openai_compat` (for `transport=="openai"`, incl. groq/mistral/openai) or the anthropic streamer with the **registry-fixed base_url + decrypted key + chosen model**. The streaming worker passes `turn.credential_id` (new column on `tutor_turn_jobs`) into `orchestrate_stream` → `stream_chat`.

**Resolution precedence + fallback (FR-BYOK-05, R-M11′):**
1. foreground ctx with active/enabled/`last_validation_status != invalid` credential → BYOK (`billing_mode="byok"`).
2. **Model-allowlist drift (R-M11/R-M11′):** if the stored `model` is no longer in `ProviderSpec.models` → if `allow_platform_fallback` → platform model + set `last_validation_status="needs_attention"` + surface `byok.model_unavailable`; else hard-fail `tutor.byok_provider_error`. Never silently dispatch a disallowed model.
3. **Auth error at dispatch** (401/403/invalid-key class) → mark credential `invalid`; if `allow_platform_fallback=true` (default) → platform for this request + one-time notice; else hard-fail `tutor.byok_provider_error`. Errors **redacted** (no vendor headers/IDs/body).
4. **Transient/rate-limit/timeout** → DO NOT fall back; surface a clean error (cost ownership stays predictable).
5. No credential / background ctx → platform.
6. **Quota-exhausted BYOK user is blocked, not routed to free platform model.**

**Provider key safety (FR-BYOK-23/25):** wrap the in-provider key in `SecretStr`; add redacting `__repr__`/`__str__` to `AnthropicProvider`/`OpenAIProvider`/`MistralProvider` so `repr(provider)` never contains the key. No process-wide/Redis cache of decrypted keys; a request-scoped cache may hold the **provider object**, dropped at request end.

### 5. Non-dollar quotas (R-M7′ / FR-QUOTA-01..03)

Two enforcement layers:

- **Pre-dispatch, DB-backed hard backstop (R-M7′):** before invoking the provider, `call_logged` (and the streaming reservation path) count `llm_calls` rows for the user in the window — **request-count and job-count, independent of `cost_usd`**. Dimensions: `requests_per_window`, `jobs_per_window`, `max_retries_per_call`, `hard per-call provider timeout`. Token-per-window is post-dispatch (we only know tokens after the call). Trip → short-circuit with `llm.quota_exceeded` (tripped dimension in `details`) + persist a sentinel `llm_calls` row `status="quota_exceeded"` (mirrors `STATUS_BUDGET_EXCEEDED`, `llm_call_log.py:230-244`; new status literal added to `models/llm_call.py`).
- **Redis concurrency lease, best-effort (R-M7′):** reuse `cost_scripts.check_concurrency`/`release_concurrency` with TTL = `llm_provider_timeout_s + buffer` so a crashed process's slot auto-expires (R-M7). **Redis-down → fail-open** for concurrency (log+metric); the DB backstop is the hard guard.

Tiers (FR-QUOTA-02, defaults R-G1, all in Settings, per-capability overridable): BYOK users get higher request/token/job limits but keep concurrency/retry/timeout caps; platform users keep the existing 24h dollar cap **plus** request/token caps. New Settings: `byok_requests_24h`, `byok_tokens_24h`, `platform_requests_24h`, `llm_max_concurrent`, `llm_max_retries`, `llm_provider_timeout_s`.

slowapi rate-limiting extends to BYOK create/update/validate (FR-QUOTA-04), keyed per-user-sub→IP via existing `_identity_key` (`ratelimit.py:34`).

### 6. Validation probe + key-oracle caps (FR-BYOK-19, R-S4)

`POST /me/llm-credentials/{provider}/validate` runs the cheapest authoritative auth check against the **registry-fixed base URL** (`chat_min`: `max_tokens=1` completion). SSRF-safe by construction. Updates `last_validated_at`/`last_validation_status`; returns `{status, message}` with **normalized/redacted** message (no vendor headers, request-ids, rate-limit hints, raw bodies, key echo). **Anti-oracle (R-S4):** a key must be **stored (encrypted) before/at validation** (no validate-without-store); cap **≤5 validations / 10 min → 429 `byok.validate_rate_limited`**, and **≤10 distinct `key_fingerprint`s validated per user / day** (counts distinct fingerprints in `byok.credential_validated` audit window) → 429; flag rapid rotate+validate for review. Auto-run validate **at most once on create**; no auto-revalidate loop.

### 7. Redaction filter over all sinks (R-U3 / FR-BYOK-24)

A **value-level redaction processor** registered as the **last** structlog processor (after `_redact`, `logging.py:73`) and applied to exception/trace serializers. It walks `event_dict` values (recursing into dicts/lists/str) and replaces any substring matching the **active-credential ciphertext-independent sentinel set** — implemented as: (a) a contextvar holding the set of in-flight decrypted-key hashes is impractical, so instead the filter scrubs by **pattern + known-prefix** (`sk-`, `sk-ant-`, `gsk_`, etc.) AND a test-injected sentinel. The tested contract per R-U3 is **enumerated-path coverage with a known sentinel key**: a fixture sets a sentinel "key" into a credential, drives each named sink, and asserts the sentinel is absent across: structlog output, exception messages/tracebacks to client, `llm_calls` rows, `agent_traces`/`retrieval_audits`/`tutor_turn_jobs`/`tracing.py` sinks, sub-agent trace payloads, Celery task payloads/args, admin views, OpenAPI schema, `/me/export`. The error envelope (`{error:{code,message,details,request_id}}`, `errors.py:123`) scrubs `details`. The filter wraps **worker** structlog/exception/trace sinks too (R-S1′f). Removes the self-defeating runtime leak-canary (R-U4) in favor of these direct tests.

## Data model changes

### New model — `app/models/user_llm_credential.py` (add to `models/__init__.py`)

```
user_llm_credentials
  id              String(21)  PK  (nanoid via IdMixin)
  user_id         FK users.id ON DELETE CASCADE, indexed
  provider        String(32)  NOT NULL          # registry key
  model           String(128) NOT NULL
  enc_key         LargeBinary NOT NULL           # BYTEA nonce‖ct‖tag (API key)
  enc_data_key    LargeBinary NOT NULL           # BYTEA wrapped DEK
  key_version     Integer     NOT NULL
  key_fingerprint String(64)  NOT NULL           # SHA-256 hex of plaintext
  last4           String(8)   NOT NULL
  enabled         Boolean     NOT NULL server_default true
  is_active       Boolean     NOT NULL server_default false   # ≤1 active per user
  last_validated_at        DateTime(tz) NULL
  last_validation_status   String(20)  NOT NULL server_default 'unvalidated'
                           # unvalidated|valid|invalid|error|needs_attention
  allow_platform_fallback  Boolean NOT NULL server_default true   # FR-BYOK-06 / R-M11′
  created_at/updated_at (TimestampMixin)
  deleted_at      DateTime(tz) NULL               # soft-delete
```
There is **no** plaintext key column, ever. No `api_base`/`host`/URL column.

Constraints/indexes:
- `uq_user_llm_credential_provider`: **partial** unique `(user_id, provider) WHERE deleted_at IS NULL` (FR-BYOK-08).
- `uq_user_llm_credential_active`: partial unique `(user_id) WHERE is_active AND deleted_at IS NULL` (≤1 active per user).
- index `ix_user_llm_credentials_user` on `(user_id)`.

### Changed model — `llm_calls` (`models/llm_call.py`)
- Add `billing_mode String(16) NOT NULL server_default 'platform'` (`platform|byok`, FR-BYOK-27).
- Add status literal `STATUS_QUOTA_EXCEEDED = "quota_exceeded"`.
- Preserve `SYSTEM_USER_ID` + both composite indexes.

### Changed model — `tutor_turn_jobs`
- Add `credential_id String(21) NULL` FK `user_llm_credentials.id` ON DELETE SET NULL — the foreground-locus token carried to the streaming worker (R-S1″). Never the key.

### Migrations (ordered, ≥0030; zero-downtime against LIVE prod DB + running fleet)

S5 is largely independent of S1/S2 (charter §4) but ships after the visibility migrations claim 0030–003x; BYOK uses the **next free numbers**. The strictly-additive nature means ordering relative to other streams is flexible; within S5 the order is:

1. **0030_byok_credentials** — `CREATE TABLE user_llm_credentials` + indexes. Purely additive; no fleet coordination. Down: drop table.
2. **0031_llm_calls_billing_mode** — `ADD COLUMN billing_mode ... server_default 'platform' NOT NULL`. Postgres 17 fast-default (no table rewrite). Old fleet writes rows without the column → DB fills the default = `platform` (correct: pre-deploy traffic is platform). New code reads it. **No NOT-NULL backfill window needed.** Down: drop column.
3. **0032_tutor_turn_credential_id** — `ADD COLUMN credential_id ... NULL` + FK. Additive, nullable. Down: drop column/FK.

**Deploy ordering (running fleet, no downtime):** migrations 0030–0032 are all additive → apply **before** rolling the new image. Old pods ignore the new table/columns; new pods use them. BYOK write/resolve paths are **flag-gated** (`feature_byok_enabled`, default OFF) so the code can deploy inert and be enabled after the fleet is fully rolled and the KEK is confirmed present on every API+worker process (R-S2 precondition + R-S3 boot guard). No down-migration is destructive; rollback = image rollback (credential rows are inert without the new code).

## API changes

All under `/api/v1`, authenticated (anonymous → 401, FR-BYOK-22). Routes registered in `app/api/router.py`; handlers `app/api/v1/llm_credentials.py` + `llm_providers.py`. Service-layer `can_use_byok` checked on every endpoint (R-CAP: pure function over `User.is_active`; suspension-only revocation).

| Endpoint | Behavior | Errors |
|---|---|---|
| `GET /llm-providers` | Registry display names + allowed models (no keys). FR-BYOK-20. | 401 |
| `GET /me/llm-credentials` | List **masked** DTOs. `api_key` field **absent** from schema. FR-BYOK-17. | 401 |
| `PUT /me/llm-credentials/{provider}` | Upsert `{model, api_key(write-only), allow_platform_fallback?}`. Validate provider/model vs registry; encrypt+store; `last_validation_status=unvalidated`; auto-validate once. Idempotent on `(provider,model,key_fingerprint)`. Emits `byok.credential_created`/`_updated`. FR-BYOK-16. | 422 `byok.base_url_forbidden` (any URL field), 422 `byok.model_not_allowed`, 422 `byok.provider_not_allowed`, 403 `byok.capability_revoked` |
| `PATCH /me/llm-credentials/{provider}` | Toggle `enabled` / set-clear `is_active` / `allow_platform_fallback`. FR-BYOK-18. | 404 `byok.credential_not_found` |
| `DELETE /me/llm-credentials/{provider}` | Soft-delete (`deleted_at`), clear active; emits `byok.credential_deleted`; resolution falls back to platform. FR-BYOK-18. | 404 |
| `POST /me/llm-credentials/{provider}/validate` | Probe; update status; redacted `{status,message}`; emits `byok.credential_validated` (status only). FR-BYOK-19, R-S4. | 429 `byok.validate_rate_limited`, 412 `byok.must_store_before_validate` |

**Pydantic v2 schemas** (`app/schemas/llm_credential.py`):
- `LLMCredentialUpsert(model: str, api_key: SecretStr, allow_platform_fallback: bool = True)` + `model_config` rejecting extras; a `field_validator` that 422s on any `base_url|api_base|host|url` key (FR-BYOK-14).
- `LLMCredentialPublic(provider, model, last4, enabled, is_active, last_validated_at, last_validation_status, allow_platform_fallback, created_at)` — `ConfigDict(from_attributes=True)`; **no** `api_key`/`enc_*`/`key_version`.
- `ProviderRegistryOut(providers: list[ProviderInfo])`.

**Error codes (new):** `byok.base_url_forbidden`, `byok.model_not_allowed`, `byok.provider_not_allowed`, `byok.credential_not_found`, `byok.validate_rate_limited`, `byok.must_store_before_validate`, `byok.capability_revoked`, `byok.model_unavailable`, `tutor.byok_provider_error`, `llm.quota_exceeded`. All via `AppError` subclasses (`errors.py:35-118`); `details` scrubbed by the redaction filter.

BYOK key material excluded from `GET /me/export` (masked metadata only) and admin user/LLM-call views (FR-BYOK-21). Regenerate the TS client (`make api-client`) — OpenAS contract change.

## Service / worker changes

- **`app/services/llm.py`:** `get_provider()` keeps its zero-arg signature for system/eval paths; add `build_provider_from_spec(spec, *, api_key, model)` used by `byok.build_provider`. Add `SecretStr` wrap + redacting `__repr__`/`__str__` to `AnthropicProvider`/`OpenAIProvider`/`MistralProvider` (`llm.py:200,312,460`).
- **`app/services/byok.py` (NEW):** `LLMContext`, `resolve_context`, `build_provider` (the only decrypt site), drift/fallback/quota wiring.
- **`app/services/llm_stream.py`:** `stream_chat(messages, *, ctx)` replaces the global-switch fork (`llm_stream.py:93`); dispatches by `spec.transport` using registry base + decrypted key.
- **`app/services/llm_call_log.py` `call_logged`:** add `ctx`/`billing_mode` param; add **pre-dispatch DB request/job quota** check (FR-QUOTA-01/03) alongside the existing dollar guard (`llm_call_log.py:227`); persist `billing_mode` + `quota_exceeded` sentinel rows.
- **Call-site threading (pass `ctx`):** `tutor_orchestrator.py:654`, `authoring_orchestrator.py:484`, `learning_path.py:757` (+ handlers `:181`/`:271` resolve foreground ctx), `concept_explainer.py:110`, `quiz_generator.py`, `orchestrate_stream`/`tutor_streaming.run_turn` (carry `credential_id`).
- **`replan_for_user`:** add `ctx: LLMContext = PLATFORM_CONTEXT`; API passes foreground ctx, beat (`workers/tasks/learning_path.py:70`) passes default (R-S1″).
- **`app/core/secrets_crypto.py` (NEW):** encrypt/decrypt/fingerprint/last4/rotate.
- **`app/core/prod_guards.py`:** `check_byok_master_key`; **`app/workers/celery_app.py`:** new `worker_init` signal running the guard (R-S3/R-S1′e).
- **`app/core/logging.py`:** register value-level redaction processor; export for worker reuse (R-U3).
- **`app/api/v1/admin_llm_calls.py`:** group/filter by `billing_mode`; platform-$ total **excludes byok** rows (`admin_llm_calls.py:170`); show BYOK adoption + non-dollar quota consumption (FR-BYOK-28).
- **`app/cli.py`:** `rotate_byok_master_key` command (FR-BYOK-12).
- **Authorizer/capability:** `can_use_byok(user) -> bool` in `app/services/capabilities.py` (= `user.is_active`; R-CAP). FR-BYOK-22's per-user revocation column is **dropped** (R-CAP) — suspension covers it; emits `byok.capability_revoked` is replaced by suspension audit. (W2 cleanup sweep, R3.)

## Frontend changes

- **Route:** `apps/frontend/src/app/profile/model/page.tsx` (new BYOK tab under the existing `/profile`) — client component; form per provider (select provider→model from `GET /llm-providers`, write-only key input, validate button, enabled/active/fallback toggles). Masked read; no key ever rendered. **No `api_base` field** anywhere.
- **Components:** `src/components/byok/CredentialForm.tsx`, `ProviderSelect.tsx`, `CredentialList.tsx`, `ValidateButton.tsx`, `NeedsAttentionBanner.tsx` (drift/auth-fallback notice).
- **Data hooks (TanStack Query):** mutations for upsert/patch/delete/validate; new keys in `src/lib/query/keys.ts`:
  ```ts
  llmProviders: ["llm-providers"] as const,
  llmCredentials: ["me", "llm-credentials"] as const,
  ```
- **i18n (flat dotted keys, `src/lib/i18n/messages/en.ts` + `ar.ts`, parity-enforced):**
  - `byok.title` — "Your model" / "النموذج الخاص بك"
  - `byok.subtitle` — "Use your own AI provider and key instead of the free platform model." / "استخدم مزوّد الذكاء الاصطناعي ومفتاحك الخاص بدلاً من نموذج المنصّة المجاني."
  - `byok.provider` — "Provider" / "المزوّد"
  - `byok.model` — "Model" / "النموذج"
  - `byok.apiKey` — "API key" / "مفتاح الـ API"
  - `byok.apiKey.writeOnly` — "Stored encrypted. Never shown again." / "يُخزَّن مشفّرًا. لن يُعرض مرة أخرى."
  - `byok.allowFallback` — "Fall back to the free platform model if my key fails" / "العودة إلى نموذج المنصّة المجاني إذا فشل مفتاحي"
  - `byok.validate` — "Validate" / "تحقّق"
  - `byok.status.valid` — "Valid" / "صالح"
  - `byok.status.invalid` — "Invalid key" / "مفتاح غير صالح"
  - `byok.status.unvalidated` — "Not validated" / "لم يتم التحقّق"
  - `byok.status.needsAttention` — "Needs attention" / "يحتاج إلى مراجعة"
  - `byok.enabled` — "Enabled" / "مُفعّل"
  - `byok.active` — "Use for my requests" / "استخدمه لطلباتي"
  - `byok.delete` — "Remove key" / "إزالة المفتاح"
  - `byok.error.modelUnavailable` — "That model is no longer available; using the platform model." / "لم يعد هذا النموذج متاحًا؛ يتم استخدام نموذج المنصّة."
  - `byok.error.providerError` — "Your provider rejected the request. Check your key." / "رفض مزوّدك الطلب. تحقّق من مفتاحك."
  - `byok.error.rateLimited` — "Too many validation attempts. Try again later." / "محاولات تحقّق كثيرة جدًا. حاول لاحقًا."
  - `byok.quota.exceeded` — "You've reached your request limit for now." / "لقد بلغت حدّ الطلبات حاليًا."

## Alternatives considered

- **User-supplied `api_base` (charter v1)** → rejected: SSRF/exfil (`llm.py:211,323`); fixed registry base closes it by construction (FR-BYOK-14).
- **Single static KEK encrypting keys directly (no DEK)** → rejected: rotation would require re-encrypting every key blob with the inner secret in memory; envelope wrapping rotates only `enc_data_key` (FR-BYOK-09/12).
- **Reuse `badges_keys.py`** → rejected: Ed25519 signing, not symmetric encryption (FR-BYOK-09).
- **Decrypt in worker once and pass plaintext in Celery payload** → rejected: payload/broker leak (FR-BYOK-26); pass `credential_id`, re-resolve in worker.
- **Classify locus by execution venue (API vs worker)** → rejected: the streaming tutor + worker replan break it (R-S1′/S1″); classify by **initiation**.
- **Dollar-only guard (status quo)** → rejected: $0 BYOK calls bypass it (`llm_pricing.py:84`, `llm_call_log.py:227`); non-dollar pre-dispatch DB quotas required (FR-QUOTA-01).
- **Redis-only quota** → rejected: Redis-down fails open; DB backstop is the hard guard (R-M7′).
- **DB-table provider registry with admin CRUD** → rejected for v1: code constant is simpler, versioned, no live-edit attack surface (R-G4); revisit if admins need runtime model curation.
- **Caching decrypted keys process-wide/Redis** → rejected: enlarges blast radius (FR-BYOK-25); request-scoped provider object only.
- **Key-name-only redaction (current `_redact`)** → insufficient; add value-level filter with enumerated-sink tests (R-U3/R-U4).
- **Per-user `can_use_byok` revocation column (FR-BYOK-22)** → dropped (R-CAP): suspension (`is_active`) covers abuse; no storage built.

## Consequences

- The worker becomes part of the KEK trust boundary (API + worker co-located on one host, docker-compose / AWS t4g.small — documented, not hidden). Worker boot now hard-fails without a real KEK once credentials exist.
- Two resolver paths (chat + stream) collapse to one `byok.build_provider` consumer — net simplification despite added module.
- Admin cost rollups become correct (platform-$ excludes BYOK); BYOK adoption + non-dollar usage become observable.
- New per-call DB quota read adds one indexed COUNT before each LLM call (cheap on `ix_llm_calls_user_created`); concurrency lease is best-effort.
- Rotation is an operational procedure with a fleet precondition (runbook).
- OpenAPI/TS-client regen required; i18n parity test must pass (en/ar).
- Tests must prove: `repr(provider)` redaction; sentinel absence across every named sink; Celery payload has no key bytes; BYOK streamed turn records `billing_mode=byok` + user model in `llm_calls`; validate oracle caps; quota trip persists sentinel row + blocks (no platform fallback); drift → platform + `needs_attention`; boot guard fires on API+worker.

## Requirements satisfied

FR-BYOK-01 … FR-BYOK-28; FR-QUOTA-01, FR-QUOTA-02, FR-QUOTA-03, FR-QUOTA-04. Resolutions: R-S1, R-S1′, **R-S1″**, R-S2, R-S3, R-S4, R-U3, R-U4, R-M7, R-M7′, R-M11, R-M11′, R-CAP, R-G1, R-G4. Charter decision 5 (+ 9 audit events for BYOK create/update/delete/validate). Aligns with FR-EMBED-03 (embeddings platform-pinned) and the W2 ADR-3 scope-widening (every user-initiated LLM feature classified).

## Open risks

- **Value-level redaction is heuristic** (prefix + sentinel patterns); a vendor key format outside the known prefixes could slip a raw log value. Mitigation: enumerated-sink tests + the structural rule that keys only ever exist inside a `SecretStr`-wrapped provider; periodic review when adding a provider.
- **DB quota COUNT under load** could become a hotspot at high QPS; mitigation: the existing `(user_id, created_at)` index + window cap; revisit with a Redis token-bucket if p95 regresses past R-U7.
- **Rotation mid-flight:** a credential resolved under KEK vN while rotation moves it to vN+1 — handled by retaining vN until rotation completes (R-S2), but a long-running streamed turn that outlives the retention window would fail; mitigation: rotation batches + retention ≥ max turn duration.
- **`allow_platform_fallback` consent semantics**: an auth-error fallback routes the user's prompt/course content through the platform key — surfaced as a one-time notice, but users may not register the data-handling implication; mitigation: explicit i18n copy + default documented as the consent control (FR-BYOK-06).
- **Registry-as-code** means a model curation change is a deploy, not an admin action (R-G4) — acceptable for v1; flagged for a future DB-backed registry ADR if churn grows.
- **Worker KEK availability**: if the worker boots before the KEK env propagates, the boot guard aborts it — correct but could cause a restart loop during a misconfigured deploy; mitigation: documented in the runbook + the same `BYOK_ALLOW_DERIVED_KEK` escape is dev-only.

Files grounding this ADR: `apps/backend/app/services/llm.py:200,312,460,478`, `apps/backend/app/services/llm_stream.py:93,181,219,297`, `apps/backend/app/services/llm_call_log.py:227,230`, `apps/backend/app/services/llm_pricing.py:52,84`, `apps/backend/app/workers/tasks/tutor_streaming.py:59,97`, `apps/backend/app/workers/tasks/learning_path.py:70,130`, `apps/backend/app/api/v1/learning_path.py:181,271`, `apps/backend/app/api/v1/ai_authoring.py:328`, `apps/backend/app/services/authoring_orchestrator.py:484`, `apps/backend/app/services/tutor_orchestrator.py:654`, `apps/backend/app/services/tutor_subagents/concept_explainer.py:110`, `apps/backend/app/core/config.py:144,264`, `apps/backend/app/core/prod_guards.py:199`, `apps/backend/app/core/badges_keys.py:67`, `apps/backend/app/core/cost_scripts.py:109,132`, `apps/backend/app/core/logging.py:20,31,73`, `apps/backend/app/models/llm_call.py:73,87`, `apps/backend/app/models/user.py:36,38`, `apps/backend/app/db/base.py:46`, `apps/backend/app/main.py:262,268`, `apps/backend/alembic/versions/2026_07_28_0029-*.py` (latest = 0029).