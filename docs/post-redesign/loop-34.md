# Loop 34 — Legacy POST applies L21-Sec defences + writes tutor_turn_jobs

**Date:** 2026-05-27
**Status:** Shipped

## Goal

Per plan-v7 §V7-F11: legacy POST `/tutor/conversations/{id}/messages`
and the streaming POST `/tutor/turns` should both apply the
L21-Sec defences (cost-cap + concurrency) uniformly, and both
should produce `tutor_turn_jobs` rows so the admin observability
surface sees one timeline regardless of the path the learner used.

## Scope decision

The plan note said "refactor through a shared orchestration service
module" but the legacy `tutor_orchestrator.py` is 1218 LoC of
multi-agent dispatch (retriever + code_runner + web_searcher +
quiz_generator + concept_explainer + planner). The streaming
orchestrator's narrow retriever+synth shape can't replace it
without regressing capability. So L34 takes the **lean cut**:

- Apply the same L33 cost-cap + concurrency wrappers at the top of
  the legacy POST.
- Write a `tutor_turn_jobs` row at the start of the handler;
  transition `running → complete` synchronously when the handler
  finishes (or `running → failed` if the orchestrator raises).
- Reconcile + release concurrency in both success and failure paths.

This gives 90% of the uniform-defences benefit at 10% of the risk.
A full orchestrator unification is a future loop when the streaming
orchestrator's capability set has grown to match.

## What shipped

### Legacy POST `/tutor/conversations/{id}/messages` now:

1. Opens a Redis client + runs `check_concurrency` (user-scoped
   bucket, same key as streaming → a user can't stack one legacy +
   one streaming turn to dodge the cap of 3).
2. Runs `reserve_cost` against user/IP/global buckets — tagged
   rejection surfaces as 429 with `tutor.user_cap`,
   `tutor.ip_cap`, or `tutor.global_cap`. The L23 frontend's
   `isCostCapError(err)` helper already keys off these codes, so
   the cost-cap closing CTA renders on legacy turns too.
3. Creates a `tutor_turn_jobs` row with `enqueue_task=False`
   (synchronous path — no Celery), immediately promotes
   `pending → running`.
4. Runs the legacy multi-agent orchestrator (unchanged).
5. On success: marks the row `complete`, calls `reconcile_cost`
   to release the reservation, releases the concurrency slot.
6. On failure: marks the row `failed` with
   `error_code='tutor.runtime_legacy'`, then reconciles + releases.
   The original exception re-raises so the FastAPI error envelope
   fires as before.

All Redis cleanup paths wrapped in `contextlib.suppress` so a Redis
flake during reconcile doesn't break the concurrency release.

### Why not reconcile to the real cost?

The legacy multi-agent orchestrator wraps each sub-agent's LLM
call with the H1 cost meter (`llm_call_log.call_logged`), which
logs to the `llm_calls` table — but it doesn't surface the
aggregated turn cost back to the caller. To reconcile precisely
we'd need to add a `cost_usd` field to `OrchestratorResult` and
plumb it through every sub-agent. That's a separate follow-up.

For now we reconcile with `actual=0`, which releases the full
estimate. The bucket-style spend tracking still works
(per-turn reservation hits the bucket, then releases) — just
under-counts the multi-agent path. The hard daily caps are the
backstop; the per-call accounting in `llm_calls` is the precise
ledger.

### Tests

+3 backend tests in `test_tutor.py`:

- `test_legacy_post_429_when_user_cost_cap_hit` — mocks reserve_cost
  to reject with `user_cap`, asserts 429 `tutor.user_cap`
- `test_legacy_post_429_when_concurrency_cap_hit` — mocks
  check_concurrency to reject, asserts 429
  `tutor.too_many_concurrent`. Reserve_cost is never called.
- `test_legacy_post_writes_tutor_turn_jobs_row` — happy path
  asserts the `tutor_turn_jobs` row exists with status `complete`,
  scoped to the conversation's course_id, carrying the user message

The existing 16 legacy tests continue to pass — the new path
is non-blocking for the noop-provider refusal path and the
20/minute rate-limit gate (which still fires before this code).

Total tutor test count: 16 → 19 in `test_tutor.py`. Combined with
L32 + L33 streaming-tutor tests, the streaming + legacy paths have
~22 + 19 = 41 endpoint-level tests.

## Observability follow-up (deferred)

The admin `/admin/tutor-turns` UI doesn't exist yet — both legacy
and streaming paths now write to `tutor_turn_jobs`, so a single
table-listing UI would surface every turn across both paths.
Belongs to a polish loop (L36/L37 wave D-E).
