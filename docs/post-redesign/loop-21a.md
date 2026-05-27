# Loop 21a — Backend streaming spine (flag OFF)

**Date:** 2026-05-27
**Scope:** The streaming-tutor architecture's producer side. Every
new endpoint + task is reachable but gated on
`feature_tutor_streaming` (default OFF). L21b flips the flag and adds
the frontend renderer.

## What shipped

### Four new HTTP endpoints under `/api/v1/tutor/turns`

| Method | Path | Purpose |
|---|---|---|
| POST | `/tutor/turns` | Open a new turn, insert `tutor_turn_jobs` row, fire `after_commit` Celery enqueue |
| GET | `/tutor/turns/{tid}/status` | IDOR-safe poll for terminal state |
| GET | `/tutor/turns/{tid}/stream` | SSE event source backed by Redis Streams with `Last-Event-ID` resume + trim detection |
| DELETE | `/tutor/turns/{tid}` | Mark `aborted` (terminal); also IDOR-safe |

All four return **503 `tutor.streaming_disabled`** when the flag is
OFF. The existing `/tutor/conversations/{id}/messages` path stays
canonical until L21b.

### Celery infrastructure

- `app/workers/tasks/tutor_streaming.py::run_turn` — task name
  `tutor.run_turn.v1`. `bind=True`, `max_retries=0`, `acks_late=True`.
  Inside: atomic phase fence via `claim_pending_turn`, `asyncio.run`
  wrapping the async orchestrator, `finally` block where every
  cleanup (release_concurrency, redis.aclose, stream TTL) is wrapped
  in `contextlib.suppress` per plan-v7 §V7-F7.
- `app/workers/tasks/tutor_sweep.py::sweep_dead_turns` — beat-scheduled
  every 10 s. Phase-ordered: Redis `RECONCILE_COST` release **first**,
  then DB `UPDATE … SET status='failed'`. If Redis fails, the row
  stays unreleased; next tick retries (plan-v7 §V7-F3). Also picks up
  already-`failed`/`aborted` rows with `reserved_cost_usd > 0` so
  prior Redis-failures eventually get cleaned up.
- `app/workers/tasks/tutor_sweep.py::cleanup_orphan_streams` — beat
  every 5 min. `SCAN tutor:turn:*` and `DEL` any whose DB row is
  terminal or missing.
- `celery_app.py` registers both new task modules + uses
  `timedelta(seconds=…)` schedules (plan-v7 §V7-F10 — `crontab(
  second='*/10')` is invalid Celery syntax).

### Pure-utility primitives

- `app/services/redis_streams.py` — `emit_event`, `consume_stream`,
  `check_trim`, `set_stream_ttl`. `MAXLEN ~ 500` cap + integer
  `<ms>-<seq>` ID comparison (plan-v7 §V7-F12). The `check_trim`
  helper is the §V7-F4 fix: `XREAD` from a trimmed offset silently
  returns next entries; we detect via `XRANGE` + the explicit
  comparison.
- `app/services/tutor_turn_service.py` — DB layer: `create_turn`
  (with `after_commit` enqueue + try/except per §V7-F6), atomic
  `claim_pending_turn` phase fence, `mark_terminal` (zeros
  `reserved_cost_usd` so the sweep doesn't double-release),
  IDOR-safe `get_turn_for_user`.
- `app/services/tutor_orchestrator_stream.py` —
  `orchestrate_stream(turn_id, …)` async generator yielding
  `planner_start` → `tool_call_start` → `tool_call_result` →
  `synth_chunk` (×N) → `turn_complete`. L21a-shippable shape is the
  noop sequence so the SSE wire format is verified end-to-end;
  AsyncOpenAI streaming integration is a deferred follow-up.

### Tests

| Surface | Tests |
|---|---|
| Endpoint flag gating + IDOR | 5 (in `test_tutor_streaming_endpoints.py`) |
| Orchestrator event sequence | 2 (in `test_tutor_streaming_orchestrator.py`) |
| **L21a total** | **7 new** |
| Backend suite (after L21-Sec + Codex rescue) | **708 / 708** green (pre-L21a was 701) |

## What did NOT ship (deferred)

- **AsyncOpenAI streaming integration.** The orchestrator yields a
  noop chunk sequence today. Wiring `client.chat.completions.create(
  stream=True, stream_options={"include_usage": True})` into the
  synth-chunk branch is a follow-up of <500 LoC.
- **Cost-cap reservation at POST time.** The Lua scripts ship in
  L21-Sec and are tested; the POST handler currently sets
  `reserved_cost_usd=0`. Layering the real `reserve_cost` call (+
  the per-IP key derivation that the sweep then uses to release) is
  another follow-up.
- **Legacy POST `/tutor/conversations/{id}/messages` refactor** to
  also write a `tutor_turn_jobs` row + run through shared
  orchestration (plan-v7 §V7-F11). Deferred to avoid bloating L21a;
  the legacy path keeps its current behaviour.
- **Frontend renderer + flag flip** — L21b.

## Verification

```
$ docker compose exec api ruff check . / ruff format --check .    # clean
$ docker compose exec api alembic upgrade head                     # no new migrations in L21a
$ docker compose exec api pytest --no-cov                          # 708 / 708 green
$ pnpm exec vitest run                                              # 53 / 289 green (unchanged)
```

## Files

**Backend new:**
- `apps/backend/app/services/redis_streams.py`
- `apps/backend/app/services/tutor_turn_service.py`
- `apps/backend/app/services/tutor_orchestrator_stream.py`
- `apps/backend/app/workers/tasks/tutor_streaming.py`
- `apps/backend/app/workers/tasks/tutor_sweep.py`
- `apps/backend/app/api/v1/tutor_streaming.py`
- `apps/backend/tests/test_tutor_streaming_endpoints.py`
- `apps/backend/tests/test_tutor_streaming_orchestrator.py`

**Backend modified:**
- `apps/backend/app/api/router.py` (register tutor_streaming router)
- `apps/backend/app/workers/celery_app.py` (register task modules +
  beat schedule entries for sweep + orphan cleanup)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L21a row)
- `docs/post-redesign/loop-21a.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L21b — Frontend streaming + flag-flip. `useSyncExternalStore` +
SSE parser + reducer + a11y + iOS UA sniff for 15.0-15.3. Flip
`feature_tutor_streaming` to True in the L21b release. Per the every-
3-loop cadence (L21a + L21b + L22 = 3 loops since last Codex), the
rescue checkpoint runs after L22.
