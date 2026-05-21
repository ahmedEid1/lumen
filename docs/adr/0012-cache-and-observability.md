# ADR-0012: Cache strategy and observability stack

- **Status:** Accepted
- **Date:** 2026-07
- **Deciders:** maintainers

## Context

Iterations 66, 70, and 71 added three layers that together define
how this service behaves at the network and observability edges.
They're cheap to add and cheap to ignore — but their behaviour
matters most when something goes wrong, so capturing the *why* once
prevents the inevitable "is this safe to remove?" review in 6 months.

## Decision

### Catalog cache headers (iter 66)

Anonymous reads of `/subjects`, `/tags`, `/courses` (list) return:

```
Cache-Control: public, max-age=60, stale-while-revalidate=300
Vary: Accept-Encoding, Authorization
```

Authenticated reads on the same routes return:

```
Cache-Control: private, max-age=0, no-store
```

The 60-second TTL is small enough that a course publish propagates
to the homepage within a minute; the stale-while-revalidate window
absorbs a thundering herd while a single origin call refreshes the
cache. `Vary: Authorization` is defensive — the body is the same
across auth and anon today, but if a future change adds a per-viewer
field, the Vary will already be set so a shared cache can't leak.

Authenticated bodies *never* sit in a shared cache. Cache-key
collision on URL alone could leak data to the next anonymous caller
hitting the same query string.

### CSP on JSON responses (iter 70)

```
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'
```

Applied via `SecurityHeadersMiddleware`, gated on
`Content-Type: application/json`. JSON doesn't render in a browser
— there's nothing to load — so the strictest possible CSP costs
nothing for legitimate API consumers. The benefit is killing the
"attacker tricks a browser into treating our response as HTML"
attack class outright.

**Not** applied to HTML responses (`/docs` Swagger UI uses inline
scripts + a CDN; a strict CSP would break it). Swagger is dev-tool
surface; the trade-off is correct.

### OpenTelemetry tracing (iter 71)

Opt-in via `OTEL_EXPORTER_OTLP_ENDPOINT`. Empty endpoint =
zero-overhead no-op (the SDK is not initialised, no spans are
created, no network traffic happens). When set:

- TracerProvider configured with `service.name` from settings and
  `deployment.environment` from env;
- BatchSpanProcessor + OTLP/HTTP exporter;
- Auto-instrumentation for FastAPI (with `/metrics` and `/`
  excluded — Prometheus scrapes add noise without signal),
  SQLAlchemy, and Redis. Together those cover essentially all
  I/O the API issues.

Init is idempotent — `uvicorn --reload` would otherwise stack a
fresh TracerProvider on every cycle.

## Alternatives considered

- **ETag/conditional GET on catalog instead of max-age.** Rejected
  for the first cut — ETag requires computing a stable body hash
  on every request, which doesn't compose well with the Pydantic
  serializer. Future ADR if we measure that the max-age cache isn't
  enough.
- **CSP on every response with a tailored policy for Swagger.**
  Rejected — Swagger's CSP requirements drift with each release and
  maintaining the whitelist would be ongoing toil for ~zero security
  benefit on a dev-only surface.
- **Always-on OTel with sampling at the exporter.** Rejected — even
  the "off" path of OTel costs something (span creation + queue),
  and projects without an OTLP receiver shouldn't pay it.

## Consequences

Positive:
- Catalog reads can be served by Caddy / Cloudflare without a DB
  round-trip ~95% of the time once the cache warms.
- JSON responses are a hardened surface even against XSS that
  somehow tricks the browser.
- Tracing is one env-var away in any environment that has a
  collector; we never have to "add OTel" again, just turn it on.

Negative:
- `Cache-Control: public` means a course publish takes up to 60s
  to show on the homepage. Acceptable for catalog UX; not for
  cart / payment flows (when those land).
- OTel auto-instrumentation can be loud — every SQL query becomes
  a span. Sampling at the collector is the standard recourse.

## References

- iter 66 (`perf(catalog): Cache-Control hints on public reads`)
- iter 70 (`sec(api): strict CSP on JSON responses`)
- iter 71 (`feat(observability): wire OpenTelemetry tracing init`)
