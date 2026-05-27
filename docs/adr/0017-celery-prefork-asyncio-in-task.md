# ADR-0017: Celery worker pool — prefork + concurrency=4, with `asyncio.run()` inside the task

- **Status:** Proposed
- **Date:** 2026-05-27
- **Deciders:** @ahmedEid1

## Context

The L21a streaming-tutor stack runs every tutor turn as a Celery task (`tutor.run_turn.v1`). The orchestration code we already ship is async — it `await`s the LLM client, the retriever, the cost meter, the Redis Streams emitter. We need to pick a Celery worker pool model that:

1. Doesn't deadlock when an async task `await`s on `asyncio.sleep(0)` or an HTTP client.
2. Survives an API container SIGTERM mid-turn — the *worker* is a separate process from the API, so the API's deploy doesn't kill in-flight turns.
3. Gives us enough concurrency to absorb a small burst of demo traffic on a t4g.small without spinning up a second worker pod.
4. Stays compatible with the LLM-client + Redis-client SSL/connection-pool assumptions, which were authored against a thread-per-task model.

Celery offers four pool models: `prefork` (the default — N child processes, one task per child), `threads`, `gevent`, and `eventlet`. Two of those (gevent/eventlet) monkey-patch the standard library, which is exactly the part that makes `asyncio.run()` inside a task brittle (`anyio` and `asyncio` both try to install their own event loop; monkey-patched I/O fights the asyncio loop).

We also considered Celery's experimental `asyncio` pool. As of 5.4 it's still tagged unstable, doesn't compose with `beat`, and the docs themselves recommend `prefork + asyncio.run()` for production.

## Decision

```python
celery_app.conf.worker_pool = "prefork"   # explicit; matches default
celery_app.conf.worker_concurrency = 4    # one task per child, 4 children
celery_app.conf.worker_max_tasks_per_child = 200  # recycle to bound memory
```

Each tutor task is implemented as a sync Celery task that calls `asyncio.run(_run_turn_async(turn_id))` once at the top. The async function does the real work; the sync wrapper handles Celery's task lifecycle. Concurrency is process-level (4 children); each child sees one turn at a time end-to-end.

## Alternatives considered

- **`threads` pool** — would let us share an LLM client + Redis pool across tasks (cheaper boot). Rejected because `asyncio.run()` inside a thread that the GIL isn't releasing during compute-heavy LLM-SDK ops creates head-of-line blocking — one slow turn starves the others.
- **`gevent` / `eventlet` pool** — monkey-patches `socket`, `ssl`, `threading`. Composes badly with our LLM client (httpx, which has its own connection pool) and with `asyncio.run()` (two event loops fighting). Documented as incompatible-by-default with the async-LLM pattern in plan-v7 §V6-F10.
- **Celery `asyncio` pool** — appealing on paper (no `asyncio.run` boilerplate), but experimental in 5.4 and doesn't play with `beat`. Worth revisiting in 5.6.
- **One worker, dedicated process** — would cap concurrency at 1; a single hung turn would block the whole demo. Rejected.

## Consequences

- **Memory:** ~80 MB per child × 4 = ~320 MB resident for the worker. Fits t4g.small (2 GB).
- **Cold-task latency:** Each child re-imports `app/services/tutor_orchestrator.py` and friends on boot, ~1.2 s. `worker_max_tasks_per_child=200` means a child recycles after ~200 turns; in the demo's expected traffic that's once a day per child, so the cold-import tax is amortised.
- **Connection pools:** Httpx + Redis pools are now child-local. No cross-task connection sharing, but no fork-safety landmines either.
- **Concurrency cap:** 4 in-flight turns per pod. L21-Sec's `CHECK_CONCURRENCY` Lua script caps *per-user* concurrency at 3, so a single bursty user can't starve 4 children either.
- **Operational signal:** A turn that runs >60 s gets killed by Celery's `time_limit`. The sweep job marks the DB row `failed` so the polling client sees a clean failure mode.

## References

- [Celery 5.4 docs — Worker pool comparison](https://docs.celeryq.dev/en/stable/userguide/workers.html#concurrency)
- plan-v7 §V6-F10 — worker pool + concurrency decision matrix
- [Anyio + Celery interaction](https://github.com/agronholm/anyio/discussions/431) — the gevent monkey-patch fight, surfaced by another async framework
