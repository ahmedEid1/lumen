# Loop 21-Sec — Security hardening (no streaming yet)

**Date:** 2026-05-27
**Scope:** Per plan-v7 §V7-Sec — everything the streaming tutor needs
to NOT do before L21a's producer lands.

## What shipped

### Defensive primitives (additive, no caller changes yet)

- **`app/core/llm_sanitize.py`** — strips Llama 3.x special tokens
  (`<|...|>`) from tool outputs before they enter the LLM prompt.
  Generic regex catches the entire reserved shape, not just the
  named alphabet. `sanitise_with_nonce_wrapper()` adds the
  nonce-fenced `<lumen-data>` envelope from plan-v7's
  indirect-injection design (orchestrator passes the nonce; the
  model is instructed to treat anything inside as data, not
  instructions).
- **`app/core/sentry_scrubber.py`** — `before_send` hook installed in
  `main.py`. Zeroes out tutor-namespace locals (`prompt`,
  `system_prompt`, `user_message`, `messages`, `tool_output`, etc.)
  from every captured frame; drops request bodies for `/tutor`-
  prefixed URLs; scrubs `category="tutor"` breadcrumbs.
- **`app/core/lua/*.lua`** + **`app/core/cost_scripts.py`** — four
  Lua scripts implementing per-user / per-IP / per-global rolling-
  24h cost caps in microcents (zero FP drift) plus
  per-user concurrent-stream counter:
  - `reserve_cost.lua` — atomic 3-bucket check + INCR with TTL-only-
    on-creation
  - `reconcile_cost.lua` — delta adjust, floored at zero, DEL when
    landing at zero so no permanent zero keys
  - `check_concurrency.lua` — INCR-with-cap on user counter
  - `release_concurrency.lua` — DECR floored at zero
- **`app/services/code_runner_subprocess.py`** — subprocess-isolated
  RestrictedPython runner. Child applies `RLIMIT_CPU` (2 s) +
  `RLIMIT_AS` (256 MB) **before** importing anything heavy, then
  runs the same sandbox the in-process runner uses. Parent
  wall-clock-times-out + SIGKILLs the process group on overrun.
  Linux-only; in-process runner stays as fallback elsewhere.

### Hard guarantees (active immediately)

- **`app/cli.py::_refuse_prod_seed_or_pass`** — `seed` and
  `demo-seed` commands now refuse in `ENV=production` unless
  `LUMEN_ALLOW_PROD_SEED=1` is set. Defends against accidentally
  inserting the fixed-password demo learner into a real prod DB.
- **Alembic 0027** — empty `tutor_turn_jobs` table (per ADR-0019)
  with `reserved_cost_usd` + `reservation_ip_key` reservation
  columns from plan-v7 §V7-F2, plus the partial index over
  `(status, updated_at) WHERE status IN ('pending','running','streaming')`
  the sweep beat job will key off.
- **Email-verify grandfather migration** in 0027 — every existing
  user gets `email_verified_at = COALESCE(email_verified_at,
  created_at)`. RETURNING captures the count + first 100 ids into
  an audit row (`auth.bulk_grandfather_email_verify`).
- **Boot-hook backstop** in `main.py` lifespan — re-runs the
  COALESCE on every API container start so the deploy-window race
  (plan-v7 §V7-F9: a user registers between migration-complete and
  the verification-gate code reaching every replica) doesn't lock
  anyone out.

### Tests

| Surface | Tests | All green |
|---|---|---|
| LLM sanitizer | 11 | ✓ |
| Sentry scrubber | 7 | ✓ |
| Lua cost scripts | 12 (Redis-backed) | ✓ |
| Code-runner subprocess | 8 (CPU/MEM/timeout kill) | ✓ |
| Tutor IDOR | 2 (POST + listing) | ✓ |
| Seed-prod refusal | 3 (dev pass / prod refuse / override) | ✓ |
| **L21-Sec total** | **43 new** | **all pass** |
| Backend suite | **697 / 697** | ✓ |
| Frontend suite | 53 files / 289 tests | ✓ |

## What did NOT ship (deferred to L21a or L21b)

- **Cost-cap callers.** The four Lua scripts are pure utility today;
  the streaming POST handler in L21a will wire them in. Per
  plan-v7's "no streaming yet" framing, the wire-up doesn't
  belong in L21-Sec.
- **Email-verify enforcement.** The grandfather migration ran; the
  gate that *checks* `email_verified_at` on the tutor endpoint
  lands with L21a (where the new POST `/tutor/turns` is added).
  Today's POST `/tutor/conversations/{id}/messages` keeps its
  existing rate-limit + auth posture.
- **System-prompt-extraction eval probes** — needs the eval harness
  refactor in L25.
- **Legacy POST refactor through a shared service** — touches
  `tutor.py` heavily; L21a will land it alongside the new
  streaming POST so they share the same orchestration module.

## Verification

```
$ docker compose exec api ruff check . / ruff format --check .   # clean
$ docker compose exec api alembic upgrade head                    # 0026 → 0027 OK
$ docker compose exec api pytest --no-cov                         # 697 / 697 green
$ pnpm exec tsc --noEmit / vitest run                             # 53 / 289 green
```

## Codex rescue cadence

Per the every-3-loop cadence inherited from the redesign: L20.5 +
L20.6 + L21-Sec = 3 loops. Codex rescue after this push lands.

## Files

**Backend new:**
- `apps/backend/app/core/llm_sanitize.py`
- `apps/backend/app/core/sentry_scrubber.py`
- `apps/backend/app/core/cost_scripts.py`
- `apps/backend/app/core/lua/reserve_cost.lua`
- `apps/backend/app/core/lua/reconcile_cost.lua`
- `apps/backend/app/core/lua/check_concurrency.lua`
- `apps/backend/app/core/lua/release_concurrency.lua`
- `apps/backend/app/services/code_runner_subprocess.py`
- `apps/backend/app/models/tutor_turn_job.py`
- `apps/backend/alembic/versions/2026_07_27_0027-0027_l21sec_grandfather_email_verify_and_tutor_turn_jobs.py`
- `apps/backend/tests/test_llm_sanitize.py`
- `apps/backend/tests/test_sentry_scrubber.py`
- `apps/backend/tests/test_cost_scripts.py`
- `apps/backend/tests/test_code_runner_subprocess.py`
- `apps/backend/tests/test_tutor_idor.py`
- `apps/backend/tests/test_seed_prod_refusal.py`

**Backend modified:**
- `apps/backend/app/cli.py` (refuse-prod helper + 2 call-sites)
- `apps/backend/app/main.py` (Sentry before_send + grandfather boot hook)
- `apps/backend/app/models/__init__.py` (re-export TutorTurnJob + constants)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L21-Sec row)
- `docs/post-redesign/loop-21-sec.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L21a — Backend streaming flag-OFF. Celery task `tutor.run_turn.v1`,
Redis Streams emit, AsyncIterator orchestrator, AsyncOpenAI
streaming, sweep beat job, orphan cleanup beat. Plus the Codex
rescue pass on the L20.5+L20.6+L21-Sec arc.
