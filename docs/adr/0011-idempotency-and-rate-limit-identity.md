# ADR-0011: Idempotency-Key contract and rate-limit identity

- **Status:** Accepted
- **Date:** 2026-07
- **Deciders:** maintainers

## Context

Two API-shaping decisions landed close together in iterations 58
(Idempotency-Key middleware) and 61 (per-user rate-limit keying).
Both touch the request-identity question: what counts as "the same
caller making the same request twice?" The decisions are related but
not identical; capturing them together prevents drift.

## Decision

### Idempotency-Key (iter 58)

Opt-in via the `Idempotency-Key` request header on mutating methods
(POST/PUT/PATCH/DELETE). Behaviour follows
draft-ietf-httpapi-idempotency-key-header:

- **Cache key** is `(user_identity_hash, method, path, key)`. The
  user identity hash is derived from the Authorization header or
  auth cookie *without* verifying the JWT (the dep system handles
  that). Hashing the raw token is sufficient to bucket sessions
  consistently — different users with the same key don't collide.
- **Replay** (same key + same body within 24h TTL) returns the
  cached response with `Idempotent-Replayed: true` so observability
  doesn't mistake the burst for a bug.
- **Conflict** (same key + different body) returns 422
  `idempotency.conflict`. Per the draft RFC, this is always an
  error — the client clearly burned the key on a different payload.
- **Only 2xx is cached.** A transient 401/5xx must not pin a
  failure into a permanent state for the user. Retry-with-same-key
  on a 4xx executes normally.
- **256 KB body cap.** Larger responses skip caching to avoid
  Redis bloat. The request still runs and the response still ships;
  replays just re-execute.
- **Skip list:** `/auth/login`, `/auth/refresh`, `/auth/logout`,
  `/metrics`, and multipart uploads. These have their own state
  machine and shouldn't memoise.
- **Redis down = fail open.** A cache outage logs a warning but
  doesn't reject the request. Refusing because the cache is
  unreachable would itself be an incident.

### Rate-limit identity (iter 61)

slowapi's default `get_remote_address` keyed every bucket by remote
IP. Two learners behind the same NAT (office, school, coffee shop)
shared one bucket — a noisy account could lock out every colleague
on the gateway.

`_identity_key` now prefers, in order:

1. JWT `sub` decoded from the Authorization header. Signature
   failures degrade silently to the next branch (a bogus token
   shouldn't raise mid-request from the limiter callback).
2. SHA-256 prefix of the auth cookie. We don't decode it — hashing
   is enough to bucket sessions consistently without needing the
   JWT secret in this callback.
3. Remote address. Old behaviour. Anonymous traffic has no other
   handle; IP is the best we have.

### Why these share an ADR

Both functions answer "who is this request?" Idempotency uses the
answer to scope a replay cache. Rate-limiting uses it to scope a
token bucket. The same forces apply: NAT-share unsafe, JWT-decode
expensive on the hot path, cookies must be hashed not decoded.
Keeping the two implementations side-by-side in this ADR makes
future drift visible — if rate-limit identity ever needs to verify
the JWT, idempotency probably does too.

## Alternatives considered

- **Idempotency-Key keyed by IP** (drop user identity). Rejected —
  two users behind NAT would have to coordinate their keys to avoid
  conflicts, which is absurd.
- **Rate-limit decoding the JWT with verification.** Rejected —
  the verification cost lands on every rate-limited request
  including the rejected ones. Signature failure on the limiter
  callback path is a no-op fall-through here; the real auth dep
  catches it for the actual handler.
- **In-memory idempotency cache instead of Redis.** Rejected for
  prod — multiple replicas wouldn't share the cache, so the same
  key hitting different replicas would re-execute the request.
  Tests use slowapi's `memory://` storage for the limiter, but
  Idempotency tests still need Redis (covered by the dev compose).

## Consequences

Positive:
- Idempotency cleanly handles the retry storm pattern (mobile flaky
  network → user mashes Submit → only one effect, replays return
  the same result).
- Rate-limit buckets are now meaningful per-account rather than
  per-tenant-LAN.
- Both decisions are documented next to each other so the next
  contributor changing one considers the other.

Negative:
- Idempotency middleware reads the request body to fingerprint it.
  Starlette's `BaseHTTPMiddleware` body re-injection is fragile;
  we have to set `request._receive` to a synthetic generator
  before `call_next` to put the bytes back. Documented in the
  middleware module.

## References

- iter 58 (`feat(api): Idempotency-Key middleware`)
- iter 61 (`fix(ratelimit): key buckets by user identity`)
- draft-ietf-httpapi-idempotency-key-header
