# Loop 32→34 Codex rescue

**Date:** 2026-05-27
**Codex CLI:** v0.133.0 (per-commit `codex review --commit <sha>`
form; the arc-form `--base` rejects positional prompts so the
focus areas went via `--title`).

## Findings + fixes

### P1 — cost-bucket key prefix mismatch with the sweep (L33)

Codex on `a1a4953`:

> [P2] Use the same cost bucket keys as the sweep —
> `apps/backend/app/api/v1/tutor_streaming.py:148-150`. These
> reservations are written under `tutor_cost:*`, but the existing
> stale-turn sweep reconciles `cost:user:*`, `cost:ip:*`, and
> `cost:global`. When a worker dies, enqueue fails, or a
> pending/running row is swept, the sweep will decrement different
> Redis keys and then zero `reserved_cost_usd`, permanently leaving
> the real `tutor_cost:*` reservation in place until TTL expiry.

This is a **functional P1**, not P2 — the sweep's whole purpose is
the safety net for crashed workers. With the prefix mismatch,
every reservation made since L33 deployed is orphaned on worker
crash.

**Fix:** changed all three new callers to use the sweep's
canonical `cost:user:`, `cost:ip:`, `cost:global` prefixes across:

- `apps/backend/app/api/v1/tutor_streaming.py:post_turn` + `cancel_turn`
- `apps/backend/app/workers/tasks/tutor_streaming.py:_run_turn_async`
- `apps/backend/app/api/v1/tutor.py:post_message` + `_release_legacy_reservation`

### P1 — reservation leak when POST fails after reserve (L33)

Codex on `a1a4953`:

> [P1] Release reservations when POST fails after reserve.
> A request with a nonexistent `course_slug` reaches the 404 path
> after reserving cost and a concurrency slot.

**Fix:** moved `course_slug` resolution BEFORE the reservation
block in `post_turn`. Also added a compensating cleanup
(`_release_reservation` closure) that runs in the outer except so
any post-reserve failure (`create_turn`, `flush`, `commit`)
releases both the cost budget and the concurrency slot before
re-raising.

Also took the opportunity to address Codex's L32 P1 on the same
file — the `course_slug` query now filters to
`CourseStatus.published` so a logged-in user can't probe
draft/archived courses' lessons by guessing slugs.

### P1 — cancel-while-pending leak (L33)

Codex on `a1a4953`:

> [P1] Clean up reservations when pending turns are cancelled. If
> the user cancels immediately after POST while the row is still
> `pending`, `mark_terminal(...aborted...)` zeros the DB
> reservation and the later Celery task hits
> `claim_pending_turn(...) is None`; with `user_id` still unset,
> the finally block skips both Redis reconcile and concurrency
> release.

**Fix:** `cancel_turn` now reads the row's `reservation_ip_key` +
`reserved_cost_usd` before marking it terminal, then issues
`reconcile_cost(delta=-reserved)` + `release_concurrency` against
Redis directly. Wrapped in `contextlib.suppress` so a Redis flake
during cleanup doesn't block the user-visible cancellation.

### P1 — legacy POST reconciled with actual=0 (L34)

Codex on `cfa5d4e`:

> [P1] Reconcile legacy turns with actual spend. For successful
> legacy multi-agent turns, passing `actual_microcents=0` makes
> `_release_legacy_reservation` apply `-estimate` and fully remove
> the reservation even though the orchestrator may have made paid
> LLM calls. ... so the new cap check can be bypassed by repeatedly
> using this endpoint.

**Fix:** the success path now passes
`actual_microcents=reserved_microcents` (zero net delta — the
estimate stays in the bucket). The bucket retains the spend until
its 24h TTL, so the cap actually applies. Precise per-call cost
still lives in `llm_calls` for billing reconciliation; the bucket
is the rolling-window cap, not the cost ledger.

### P1 — legacy POST leaks reservation on post-reserve failure (L34)

Codex on `cfa5d4e`:

> [P1] Release reservations on all post-reserve failures. After
> `reserve_cost` succeeds, failures before `ask_with_trace` enters
> its `try` block — for example `create_turn`/`flush` failing, the
> history query failing, or the user-message insert failing —
> bypass `_release_legacy_reservation`.

**Fix:** wrapped all post-reserve work (`create_turn` +
history-query + user_msg persist + orchestrator call) in a single
outer try/except. Any exception in that range marks the
`tutor_turn_jobs` row failed (when it exists) and releases the
reservation before re-raising.

## Findings deferred

- **L32 P2 (citation forgery via user prompt)** — adding an
  allow-list for `[L:<id>]` tokens emitted by the model. Belongs
  to the frontend renderer (or the eval suite's
  citation-extractor) — the orchestrator can't filter mid-stream
  without buffering, which would defeat the streaming UX.
- **L32 P2 (retriever-failure masked as empty)** — the Celery
  task's `contextlib.suppress(Exception)` around retrieval is
  intentional for the demo (better to ship an ungrounded answer
  than fail the whole turn). Adding a distinct `tool_call_result`
  `status="error"` for genuine retrieval failures is a follow-up.
- **L34 P2 (Idempotency-Key)** — the L21-Sec design called for
  Idempotency-Key support on mutating endpoints but didn't
  implement it. Cross-cutting work that belongs in its own loop.

## Verification

Local-first: `ruff check` clean, `ruff format` clean, 41 tutor-
related tests pass (test_tutor + test_tutor_streaming_endpoints +
test_tutor_streaming_orchestrator + test_tutor_terminal_race).
