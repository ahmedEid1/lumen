# Loop 33 — cost-reserve + concurrency at POST /tutor/turns

**Date:** 2026-05-27
**Status:** Shipped

## Goal

Wire the L21-Sec cost-cap + concurrency Lua scripts into the
streaming POST handler so the FEATURE_TUTOR_STREAMING=true demo
can't be DoS'd into bankruptcy. The L21-Sec primitives shipped
months ago but had no caller; L33 connects them.

Also discovered + fixed a deploy plumbing bug: the `x-api-env`
anchor in `docker-compose.prod.yml` enumerates passthrough env
vars by name, and `FEATURE_TUTOR_STREAMING` was never added —
which is why the L32 flag flip didn't activate the streaming code
in prod even after `flip-flag.yml` wrote the value to
`.env.production`. Same blind spot will bite every future
feature flag, so L33 adds the whole tutor-config family.

## What shipped

### POST /tutor/turns reservation

Before any DB writes, the handler now runs:

1. `check_concurrency(user_key, max=tutor_max_concurrent)` — cheap
   per-user slot reservation. Returns `(False, current)` if already
   at the cap → 429 `tutor.too_many_concurrent`.
2. `reserve_cost(user_key, ip_key, global_key, estimate)` against
   the three rolling-24h microcent buckets. Returns a tagged
   rejection (`user_cap` / `ip_cap` / `global_cap`) → 429 with the
   matching error code. The handler releases the concurrency slot
   before raising so a flat-broke caller can't slowly drain their
   own concurrency budget by retrying.

The successful reservation's microcent value lands on the row as
`reserved_cost_usd` (Decimal, USD = microcents / 1e6).

### Celery task reconciliation

After the orchestrator's `turn_complete` event, the task now calls
`reconcile_cost(delta = actual_microcents - reserved_microcents)`
to close the gap between the conservative estimate and reality.
On failure / abort, actual is 0, so reconcile releases the full
reservation. Wrapped in `contextlib.suppress` so a Redis flake
during reconcile doesn't trip another exception before the slot
release.

### Settings

Five new knobs under "L33 — Tutor cost caps & concurrency":

- `tutor_estimate_microcents = 5_000` — $0.005 per-turn estimate
- `tutor_cap_user_microcents = 500_000` — $0.50 / user / rolling-24h
- `tutor_cap_ip_microcents = 2_000_000` — $2.00 / IP / rolling-24h
- `tutor_cap_global_microcents = 20_000_000` — $20.00 / global / 24h
- `tutor_max_concurrent = 3` — concurrent streams per user

All overridable via env. Defaults sized for the public demo on
Groq Llama 3.3 70B (~$0.00024 per typical turn at $0.79/1M output
tokens, so ~100 turns / user / day before user-cap kicks in).

### Error classes

Four new `AppError` subclasses in `app/core/errors.py`, all 429:

- `TutorUserCapError` — `tutor.user_cap`
- `TutorIpCapError` — `tutor.ip_cap`
- `TutorGlobalCapError` — `tutor.global_cap`
- `TutorConcurrencyLimitError` — `tutor.too_many_concurrent`

The L23 frontend cost-cap closing CTA already keys off this error
shape via `isCostCapError(err)` — no frontend change needed for
the user-facing surface.

### docker-compose.prod.yml fix (the real bug)

Added 6 env vars to the `x-api-env` anchor:

- `FEATURE_TUTOR_STREAMING` (the L21a/b flag)
- `TUTOR_ESTIMATE_MICROCENTS`
- `TUTOR_CAP_USER_MICROCENTS`
- `TUTOR_CAP_IP_MICROCENTS`
- `TUTOR_CAP_GLOBAL_MICROCENTS`
- `TUTOR_MAX_CONCURRENT`
- `L21SEC_DEPLOY_TIMESTAMP` (was missing too — boot-hook cutoff)

Without these, setting them in `.env.production` had no effect.
This is why the L32 deploy verified green but
`/api/v1/runtime-flags` still reported `tutor_streaming: false` —
the flag value never reached the api container's process env.

### Tests

+5 backend tests:

- `test_post_429_when_concurrency_cap_hit` — concurrency rejection
  short-circuits without calling reserve_cost
- `test_post_429_when_user_cost_cap_hit_releases_concurrency` —
  user_cap rejection releases the concurrency slot before raising
- `test_post_429_when_ip_cost_cap_hit` — ip_cap → tutor.ip_cap
- `test_post_429_when_global_cost_cap_hit` — global_cap →
  tutor.global_cap
- `test_post_persists_reserved_cost_on_row` — the persisted
  `reserved_cost_usd` Decimal equals `estimate_microcents / 1e6`

The autouse `_stub_cost_scripts` fixture stubs the Lua wrappers
with permissive defaults; per-test the fixture yields the mocks so
cap-branch tests can flip return values.

Total streaming-tutor test count: 7 → 12 (L32+L33).

## Verification on prod

The L32 deploy left `tutor_streaming: false` because the env var
was set in `.env.production` but never forwarded to the container.
After L33 deploys, the api container's process env will include
`FEATURE_TUTOR_STREAMING=true` and `/api/v1/runtime-flags` will
finally report `{"tutor_streaming": true}`.
