# ADR-0019: Atomic phase fence + `after_commit` Celery enqueue for tutor turns

- **Status:** Proposed
- **Date:** 2026-05-27
- **Deciders:** @ahmedEid1

## Context

The L21a streaming-tutor stack creates a `tutor_turn_jobs` row in the request that POSTs a new tutor turn, then a Celery task picks the row up and runs the orchestration. Two failure modes the naive shape doesn't survive:

1. **Double execution.** Celery may redeliver a task if a worker dies mid-ack. Without a phase fence, two workers can claim the same row and run the orchestration twice — duplicate LLM cost, duplicate Redis Streams events, undefined behaviour for the consumer.

2. **Broker down at POST time.** If we synchronously `send_task(...)` inside the request handler and the Celery broker (Redis) is unreachable, the handler raises and FastAPI returns 500 *after* the DB row was committed. The client now has no `turn_id` to subscribe to but a row exists in the DB; the client retries; we leak rows.

The naive ordering — `INSERT row → commit → send_task` — fails on (2). Swapping to `send_task → INSERT row` fails on (1) because two enqueues can race the insert. The literature pattern is **transactional outbox**: write the row + an outbox entry inside the same transaction, then a separate sweep delivers the outbox. That's overkill for our scale (single Redis broker, no multi-region replication).

## Decision

Three coordinated mechanics.

### 1. Atomic phase fence on task entry

```sql
UPDATE tutor_turn_jobs
SET status = 'running', updated_at = now()
WHERE id = :turn_id AND status = 'pending'
RETURNING id;
```

The task's first action. If the `UPDATE` returns zero rows, another worker already claimed it and we exit cleanly. The `RETURNING` is the only signal that says "I, this worker, own this turn." This is a single SQL statement under PostgreSQL's default `READ COMMITTED` isolation — no `SELECT FOR UPDATE` dance needed.

### 2. `after_commit` enqueue, broker-failure-tolerant

```python
def _safe_enqueue():
    try:
        celery_app.send_task("tutor.run_turn.v1", args=[turn_id])
    except Exception as e:
        log.error("celery_enqueue_failed", turn_id=turn_id, error=str(e))
        # Row stays 'pending'; sweep marks failed in <60s; client gets
        # clean failure via /status polling.

event.listen(
    db.sync_session,
    "after_commit",
    lambda *_: _safe_enqueue(),
    once=True,
)
```

The DB row is committed *first*. The `after_commit` listener fires the enqueue *outside* the transaction (so a broker hiccup can't abort the transaction). The `try/except` ensures the listener never propagates an exception — broker-down means "no enqueue happened," not "the response is now 500." See plan-v7 §V7-F6 for the rationale.

### 3. Reservation metadata on the row + idempotent sweep

Each `tutor_turn_jobs` row stores `reserved_cost_usd` and `reservation_ip_key` set at POST time. A Celery beat job (every 10 s for pending, every 30 s for running) reads rows whose `updated_at` is older than 60 s, releases their reserved cost back to Redis (via `RECONCILE_COST`), and marks them `failed`. The release call comes *first* — if Redis is also unreachable, the row stays untouched and the next sweep retries. This is the idempotency story spelled out in plan-v7 §V7-F3.

## Alternatives considered

- **Transactional outbox table** — correct, but heavier: a separate `outbox_events` table, a dedicated outbox-poll job, schema for retry counts. The combined cost is more code + ops surface than `after_commit + sweep` gives us, with no extra durability in our single-broker world.
- **`SELECT … FOR UPDATE SKIP LOCKED`** — would let multiple workers safely poll the table for `pending` rows. Cleaner if we ever stop using Celery, but it shifts the "is broker reachable" question to "is the workers' poll loop running" — same problem in different clothing.
- **Pessimistic application-level lock (e.g. `pg_try_advisory_xact_lock(:turn_id_hash)`)** — works as a phase fence; the `UPDATE … WHERE status='pending'` form is equivalent and doesn't add a new locking surface.
- **Synchronous `send_task` inside the handler** — original sketch; fails the broker-down case as described above.

## Consequences

- **POST always returns 201 with `turn_id`** as long as the DB write commits. Broker-down still surfaces to the user — but as a clean polling-path failure, not a 5xx.
- **Sweep is the durability backstop.** Anything that goes pending without ever running gets marked failed within 60 s. The client's polling loop sees a definitive `failed` status with `error_code='tutor.worker_died'` and surfaces a retry CTA.
- **Phase fence is one SQL statement; double execution is impossible** under `READ COMMITTED` because the second `UPDATE` finds `status='running'` and returns 0 rows.
- **`once=True` on the listener** means a re-flush of the session can't re-enqueue. Important for the legacy POST path (which writes the same job row + flushes mid-handler before the final commit).
- **`reserved_cost_usd` + `reservation_ip_key`** are the columns the sweep reads to release the reservation atomically; their lifecycle is set-at-POST, zeroed-after-success/sweep. See ADR-0018 for the Redis Streams emitter side.

## References

- plan-v7 §V7-F3 — sweep idempotency on Redis failure
- plan-v7 §V7-F6 — `after_commit` enqueue with try/except
- plan-v7 §V7-F1 — `release_concurrency(user_id, ...)` correction (user-scoped, not turn-scoped)
- plan-v7 §V7-F2 — reservation metadata columns
- ADR-0017 — Celery worker pool (consumer side of this contract)
- ADR-0018 — Redis Streams (event substrate)
