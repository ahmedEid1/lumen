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
- Password policy: min 12 chars, against haveibeenpwned k-anonymity API (optional, configurable).
- Lockout: 5 failed logins → 15 min IP+account cooldown.
- Refresh tokens single-use; reuse triggers full chain revocation and security email.
- Optional 2FA (TOTP) post-MVP — schema already supports it.

### Data
- PII columns marked in models; logging filter redacts emails by default.
- GDPR endpoints: `GET /api/v1/users/me/export` (background job → email link) and `DELETE /api/v1/users/me`.
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

### Dependencies
- Renovate weekly; Dependabot security alerts.
- Trivy scans built images; SBOMs (CycloneDX) per release.

### Logging
- JSON structured; no full request bodies; no Authorization headers; emails redacted.
- Request IDs propagated; PII fields explicitly excluded from logging filter.

## Disclosure

Found something? Open a private GitHub Security Advisory or email `security@lumen.example`. We aim to acknowledge within 2 business days.
