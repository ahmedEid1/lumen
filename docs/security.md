# Security model

Lumen ships as a public-facing learning platform. This document is the
authoritative map of every control that protects the service in
production — `CLAUDE.md` is the short-form orientation, this file is
the long form. Updated for Phase H6 (production hardening, May 2026).

## Auth model at a glance

| Client kind | Access token transport | Refresh token transport |
|-------------|------------------------|--------------------------|
| Browser (SPA) | `__Host-access` cookie (`Secure`, `HttpOnly`, `SameSite=Strict`) in prod; `access` cookie in dev | `__Host-refresh` cookie / `refresh` cookie in dev |
| API client (CLI / mobile / server-to-server) | `Authorization: Bearer <jwt>` | `Authorization: Bearer` against `/auth/refresh` with the refresh token in the body — or the cookie if the client persists it |
| WebSocket (chat, notifications) | `?token=<jwt>` query param (browsers can't set headers on WS handshakes) | Refresh out-of-band via the HTTP API; the WS upgrade itself never carries a refresh token |

Token lifetimes:

* **Access JWT** — 15 minutes, HS256 signed with `JWT_SECRET`, issuer
  `lumen`, `sub = user_id`, `role` claim. The JWT is opaque to the
  frontend; it round-trips back to the API on every authenticated call.
* **Refresh** — 14 days, opaque random 48-byte URL-safe string,
  SHA-256-hashed at rest. Rotates on every use; the previous value is
  marked `revoked_at` with a `replaced_by_id` pointer.

## Threat model (STRIDE summary)

| Threat | Mitigation |
|--------|-----------|
| Spoofing | Argon2id passwords, JWT signed (HS256, rotating signing key planned), refresh rotation with reuse detection |
| Tampering | Pydantic validation at the edge; ORM bound parameters; signed cookies; HSTS |
| Repudiation | Audit log for admin actions and security-sensitive operations |
| Information disclosure | RBAC at dependency layer; PII redaction in logs; HTTPS only; SSO cookies `__Host-` prefixed |
| Denial of service | slowapi rate limits, request body size cap, async I/O, query timeouts, queue depth alarms |
| Elevation of privilege | Roles checked in service layer, not just routes; admin endpoints require step-up auth (re-enter password within 5 min) |

## Controls

### Transport
- TLS 1.3 only (Caddy); HSTS preload-ready (`max-age=63072000; includeSubDomains; preload`).
- HTTP/2 + HTTP/3 enabled.

### Headers (Next.js + Caddy)
- `Content-Security-Policy` strict, with `nonce`-based scripts.
- `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`.
- CORS: allow-list of front-end origin only.

### Auth
- Password policy: min 12 chars, mixed character classes; HIBP k-anonymity check optional.
- Lockout: 5 failed logins → 15 min IP+account cooldown.
- **No login enumeration**: the authenticate path always runs one Argon2
  verification — against a real or a precomputed dummy hash — so the
  wire-time latency for "no such email" and "wrong password" is dominated
  by the same CPU work. Locked in by `tests/test_login_timing.py`.
- Refresh tokens single-use; reuse triggers full chain revocation. Active
  sessions are listed at `GET /api/v1/users/me/sessions`; users can revoke
  one (`DELETE /me/sessions/{id}`) or all (`DELETE /me/sessions`).
- **Refresh-reuse alarm (H6)**: every reuse-detection event also writes
  an in-app notification (kind `security.refresh_reuse`) to every active
  admin, with the affected user's email, the IP that presented the
  reused token, and the original token's issue / revoke timestamps in
  the `data` blob. The notification is best-effort — a write failure
  is logged but never breaks the auth path. Covered by
  `tests/test_refresh_reuse_alarm.py`.
- **Password change** (`POST /me/change-password`) requires the current
  password and revokes every refresh token to force re-auth everywhere.
- **Password reset** (`POST /auth/password-reset/request|confirm`) uses a
  stateless JWT bound to the user's current password hash, so each link is
  single-use and a successful reset invalidates outstanding links.
- **Email verification** (`POST /auth/verify/request|confirm`) uses a
  stateless JWT bound to the user's current email — changing the email
  invalidates outstanding tokens; replays are idempotent.
- Optional 2FA (TOTP) post-MVP — schema already supports it.

### Rate limiting
- `slowapi` is mounted as middleware with a Redis-backed bucket (memory in
  tests). Per-IP limits today:

  | Endpoint | Limit |
  |----------|-------|
  | `POST /api/v1/auth/login` | 10 / minute |
  | `POST /api/v1/auth/register` | 5 / minute |
  | `POST /api/v1/auth/password-reset/request` | 3 / minute |
  | `POST /api/v1/auth/verify/request` | 3 / minute |

- Over-limit responses use the standard error envelope with
  `code: "rate_limited"` and carry a `Retry-After: 60` header.
- Reverse proxy `X-Forwarded-For` is trusted for the key; operators behind
  a load balancer that doesn't set XFF should adjust the proxy config.
- **429 metrics (H6)**: every 429 is recorded into an in-memory ring
  buffer (`app/core/rate_limit_metrics.py`); the admin endpoint
  `GET /api/v1/admin/rate-limit-stats?since=<epoch>` exposes
  `{endpoint: count}` so the H7 observability dashboard can show
  rate-limit pressure per route. The counter is process-local and
  resets on redeploy — when Lumen scales beyond one Fly machine the
  endpoint will switch to a Redis sorted-set without changing the
  response shape.

## LLM cost guard

LLM calls (RAG tutor, AI authoring, eval-as-judge) all route through
`app.services.llm` and are metered by H1 in the `llm_call_log` table:
prompt + completion token counts, model, latency, status, and the
cents-equivalent cost are persisted per call. Two related controls:

- **Daily / per-user cost cap** (H1) — once a learner hits the cap the
  next call returns a 429 with `code: "llm_budget_exceeded"`. The cap
  also defends against a curious visitor running a bad-actor loop
  against the public demo.
- **Provider abstraction** — the same metering powers swaps between
  Anthropic (paid), OpenAI (paid), and Groq Llama-3.3-70B (free tier;
  the v2 demo default — see `docs/superpowers/specs/2026-05-22-lumen-v2-agentic-positioning.md`
  §8).

The H6 production guard refuses to boot with `LLM_PROVIDER=noop` so a
demo that's accidentally pointed at the canned-text test provider
can't ship.

## Production boot guards

In addition to `Settings.assert_production_ready()` (dev-default
detection), `app/core/prod_guards.py` runs a second pass at startup
when `ENV=production`. The guard refuses to boot if any of these are
true:

| Check | Hard / Soft | Why |
|-------|-------------|-----|
| `LLM_PROVIDER == "noop"` | hard | Ships a demo that silently returns canned text. |
| `len(SECRET_KEY) < 32` | hard | HS256 / RFC 7518 §3.2 floor — short keys are guessable. |
| `len(JWT_SECRET) < 32` | hard | Same rationale; JWT signing key. |
| `DATABASE_URL` contains `localhost` / `127.0.0.1` / `::1` / `0.0.0.0` | hard | Catches staging-misconfig-as-prod. |
| `CORS_ORIGINS` empties out after stripping loopback / `.test` | hard | Browsers couldn't reach the API. |
| `LLM_PROVIDER=openai` with the OpenAI default `OPENAI_API_BASE` | **soft warn** | Operator probably meant Groq's `/openai/v1`. |

Soft warnings route through `structlog` at startup so the operator
sees them even when the boot succeeds.

### Data
- PII columns marked in models; logging filter redacts emails by default.
- GDPR endpoints: `GET /api/v1/users/me/export` and `DELETE /api/v1/users/me`
  (password required; scrambles PII, deactivates the account, revokes all
  refresh tokens).
- Public **certificate verification** at `GET /api/v1/certificates/verify/{id}`
  intentionally returns only the learner's *display name* and the course
  metadata — never the email or any other PII.
- Backups encrypted at rest (operator-provided).

### Application
- Output encoding by React; Markdown rendered through a sanitizer (`DOMPurify`).
- File uploads constrained by MIME + magic bytes server-side; max size enforced; AV scan hook (ClamAV image optional).
- Object storage uses presigned URLs with short TTL; bucket is private.
- Idempotency keys retained for 24 h to prevent double-submit replay attacks.

### Secrets
- Never in repo; `.env` is git-ignored; production secrets via the operator's secret store.
- `gitleaks` runs on pre-commit and CI.
- Signing keys rotated every 90 d (planned; manual via `make rotate-jwt`).
- **Startup guard**: `Settings.assert_production_ready()` refuses to boot
  when `ENV=production` if `SECRET_KEY`, `JWT_SECRET`, or
  `S3_SECRET_ACCESS_KEY` are still the dev defaults, or if `CORS_ORIGINS`
  contains `localhost`. Covered by `tests/test_config_guard.py`.
- **Secret rotation procedure**:
  1. Generate the new value: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  2. Update the secret in the operator's secret store (Fly secrets,
     Vercel project env, GitHub Actions, …).
  3. Trigger a rolling redeploy. The API picks up the new value via
     `get_settings()` at process start.
  4. For `JWT_SECRET` specifically: every in-flight access token signed
     with the old secret becomes invalid immediately. Browsers refresh
     transparently against their (cookie-stored) refresh token; CLI /
     server-to-server clients must re-authenticate. This is the
     intended blast radius for a rotation — anything else would mean
     the old key is still trusted somewhere.

### CORS policy

Allow-list driven by `CORS_ORIGINS`. The H6 boot filter strips
loopback / `.test` entries in production so a stray dev origin can't
slip through into a live deploy. If the filtered list is empty the
boot fails hard with `Production CORS_ORIGINS must include at least
one non-loopback origin`. `allow_credentials=True` so cookie-authed
mutations from the frontend work; the `CSRFOriginMiddleware` further
checks the `Origin` header against the same allow-list for any cookie-
authenticated mutating method.

### Dependencies
- Renovate weekly; Dependabot security alerts.
- Trivy scans built images; SBOMs (CycloneDX) per release.

### Logging
- JSON structured; no full request bodies; no Authorization headers; emails redacted.
- Request IDs propagated; PII fields explicitly excluded from logging filter.

## Threat model (one-page summary)

A focused recap of the STRIDE table above, scoped to the v2 single-VM
public demo (AWS t4g.small per [`docs/deployment/aws-vps.md`](deployment/aws-vps.md);
free LLM tier via Groq's OpenAI-compatible endpoint).

**Assets.** Learner accounts (email + Argon2id hash + course progress
+ certificate VCs); instructor course drafts; admin observability /
audit log; LLM API keys; the signing keys (`SECRET_KEY`, `JWT_SECRET`,
`BADGES_SIGNING_KEY`); object-storage assets (course media, learner
uploads).

**Adversaries.**

| Adversary | Plausible goals | In-scope mitigations |
|-----------|----------------|----------------------|
| Curious visitor (anonymous) | Probe for endpoints, fingerprint stack, cheap LLM cost-burn | Anon rate limits, login-timing flattening, no `Server` header, LLM cost guard, public certificate verifier returns no PII |
| Malicious learner (authenticated) | Privilege escalation to instructor / admin, scrape other learners' data, abuse the AI tutor, replay refresh tokens | Roles enforced in services (not just routes), refresh-reuse → chain revocation + admin alarm, per-user rate limits, idempotency keys, GDPR scoping (`/users/me/*` only reads own data) |
| Malicious instructor | Tamper with other instructors' courses, inject XSS through course content, exfiltrate learner reviews | RBAC at the service layer, ownership checks per resource, Markdown sanitised via DOMPurify on the client + safe rendering on the server, course-scoped reviews |
| Compromised API key (LLM / S3 / SMTP) | Cost burn, message tampering, content tampering | Cost cap (H1), short-TTL presigned URLs, distinct keys per environment, secret rotation procedure above, audit log records every admin action |

**Out of scope.**

* **DDoS at the network layer** — Cloudflare / Fly handle L3/L4; the
  app's rate limiter is application-layer only.
* **Supply-chain attacks** — Renovate + Dependabot + Trivy on built
  images + `gitleaks` cover the practical surface; full SBOM
  attestation lives with the host.
* **State-actor adversaries** — out of scope for a learning platform.

## Disclosure

Found something? Open a private GitHub Security Advisory or email `security@lumen.example`. We aim to acknowledge within 2 business days.
