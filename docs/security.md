# Security model

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
- Refresh tokens single-use; reuse triggers full chain revocation. Active
  sessions are listed at `GET /api/v1/users/me/sessions`; users can revoke
  one (`DELETE /me/sessions/{id}`) or all (`DELETE /me/sessions`).
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

### Dependencies
- Renovate weekly; Dependabot security alerts.
- Trivy scans built images; SBOMs (CycloneDX) per release.

### Logging
- JSON structured; no full request bodies; no Authorization headers; emails redacted.
- Request IDs propagated; PII fields explicitly excluded from logging filter.

## Disclosure

Found something? Open a private GitHub Security Advisory or email `security@lumen.example`. We aim to acknowledge within 2 business days.
