# ADR-0004: JWT access + rotating opaque refresh

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

We need an auth scheme that works for:
- The SPA / SSR frontend (cookies + fetcher).
- Programmatic API clients (Bearer header).
- WebSocket connections (no header support in browsers → query parameter).
- Future mobile clients.

We also want fast permission checks per request without round-tripping to Postgres, while still being able to revoke sessions.

## Decision

- **Access token:** JWT (HS256), 15-minute TTL. Claims: `sub`, `iat`, `exp`, `role`, `jti`. No PII beyond `sub` (the user id).
- **Refresh token:** opaque 32 random bytes, hashed (`sha256`) and stored in `auth_refresh_tokens` with `user_id`, `expires_at`, `revoked_at`, `replaced_by`. 14-day sliding window, single-use, rotated on every refresh. **Reuse of a revoked token** invalidates the entire descendant chain and emails the user.
- **Transport:** cookies for browser (`__Host-access`, `__Host-refresh`, `Secure`, `HttpOnly`, `SameSite=Strict`); Bearer for API clients; `?token=` for WebSockets (token is short-lived).
- **Signing key rotation:** key id (`kid`) in JWT header; `JWT_KEYS_JSON` env supports overlap during rotation.

## Alternatives considered

- **Sessions only (Redis-backed)** — simpler, but requires server I/O on every request and complicates non-browser clients.
- **Long-lived JWT only** — can't revoke; we'd have to add a denylist anyway, defeating the simplicity.
- **OAuth2 device + client credentials only** — overkill for our two client types at v1; we may layer it on later for partner integrations.

## Consequences

- Refresh rotation needs careful concurrency handling (use a serializable transaction or `SELECT … FOR UPDATE` on the token row).
- Signing key compromise is bounded by access TTL (15 min) once we rotate.
- We can sign out a single device by revoking its refresh token chain; "log out everywhere" revokes all chains for the user.

## References

- [OWASP JWT Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
- [Refresh token rotation](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)
