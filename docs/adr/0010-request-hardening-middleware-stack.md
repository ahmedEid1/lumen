# ADR-0010: Request hardening middleware stack

- **Status:** Accepted
- **Date:** 2026-06
- **Deciders:** maintainers

## Context

`create_app()` originally wired only CORS, GZip, request-id, and
access-log middleware. Iters 51, 57, and 58 added three more layers
that together constitute the request-hardening stack. The order
matters and is worth documenting.

## Decision

Middleware are registered in this order (outermost first; on the
request the OUTERMOST runs first, on the response the INNERMOST
runs first):

1. `AccessLogMiddleware` — outer-most. Times the *whole* request
   including all other middleware so the latency histogram captures
   the real user-visible cost.
2. `CSRFOriginMiddleware` — refuses cookie-authenticated mutations
   that don't come from an allow-listed Origin (iter 57). Bearer
   requests pass through.
3. `IdempotencyMiddleware` — opt-in via `Idempotency-Key` header
   (iter 58). Replay returns the cached 2xx response with
   `Idempotent-Replayed: true`; key reuse with a different body
   returns 422.
4. `SecurityHeadersMiddleware` — sets `X-Content-Type-Options`,
   `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and
   (in prod) HSTS on every response (iter 51).
5. `RequestIdMiddleware` — propagates `X-Request-ID` for tracing.
6. `GZipMiddleware` — innermost. Compresses bodies ≥ 1 KB.
7. `SlowAPIMiddleware` — provided by slowapi, registered first so
   it wraps the route handler directly. Sees rate-limit annotations.
8. `CORSMiddleware` — handles preflight and cross-origin response
   headers.

### Why this order

- **CSRF before Idempotency**: idempotent replay should not be
  available to a CSRF'd request. Reject the bad-Origin request
  before we touch the cache.
- **Idempotency before SecurityHeaders**: a replay must serve the
  cached headers as-is (we strip Set-Cookie / request-id /
  content-length explicitly). The outer SecurityHeaders pass adds
  the static headers fresh on every response, including replays —
  this is correct because the static headers are deterministic.
- **SecurityHeaders before GZip**: GZip needs to set
  `Content-Encoding` on the response without our middleware
  setdefault overriding it.
- **AccessLog outermost**: captures the latency cost of every other
  middleware, including idempotency cache hits (which should be
  visibly faster in the histogram).

## Alternatives considered

- **Single composite middleware** that did all four. Rejected —
  composability suffers and each piece has a different operational
  triage path (HSTS misfire vs CSRF misfire vs Redis-down vs CORS
  misconfig).

## Consequences

Positive:
- The response side of every request runs through a known set of
  contract layers — security headers, request-id propagation, gzip,
  CORS — in a deterministic order.
- Adding a new middleware = inserting at the right point in the list
  documented here.

Negative:
- Five middleware layers add a constant overhead per request
  (~0.3 ms in dev tests). The histograms in Prometheus pick this up.

## References

- iter 51 (`sec(api): defense-in-depth security headers`)
- iter 57 (`sec(api): Origin-header CSRF guard`)
- iter 58 (`feat(api): Idempotency-Key middleware`)
