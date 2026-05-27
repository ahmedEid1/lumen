# ADR-0018: Redis Streams (XADD/XREAD), not pub/sub, for SSE tutor replay

- **Status:** Proposed
- **Date:** 2026-05-27
- **Deciders:** @ahmedEid1

## Context

The L21a streaming-tutor stack needs a pipe between the Celery worker that runs an orchestration turn and the FastAPI process holding the open SSE connection back to the client. Because we run multiple API replicas behind the prod Caddy proxy, the worker and the SSE handler are *not* the same process — a tutor turn POSTed to one replica may be subscribed-to from a second one. Redis is the only shared substrate.

The first sketch used Redis pub/sub (`PUBLISH tutor:turn:{id}` / `SUBSCRIBE`). It works for the happy path: subscribe before publish, receive every event. It fails for the second-most-common path:

- The SSE connection drops mid-stream (mobile network blip, proxy hiccup).
- The client reconnects with `Last-Event-ID: <last-seen>` per the SSE spec, expecting replay.
- **Pub/sub has no replay.** Anything published while we were disconnected is gone. The client is stuck — it can't tell whether it missed events or there were no events to miss.

We also need `XLEN`-style observability ("how many entries in this stream?" for operational dashboards) and stream-level TTL so a forgotten turn doesn't sit in Redis forever.

## Decision

Use Redis Streams (`XADD` / `XREAD`) for tutor turn events.

- Producer (Celery worker): `XADD tutor:turn:{tid} MAXLEN ~ 500 * event <name> data <json-payload>` per event.
- Consumer (FastAPI SSE handler): `XREAD BLOCK 30000 STREAMS tutor:turn:{tid} <last-event-id>`. The last-event-id is whatever the client sent via the `Last-Event-ID` header (or `$` for "new from now" on first connect).
- TTL: `EXPIRE tutor:turn:{tid} 300` on `turn_complete` (5 min replay window). 24 h hard cap via the orphan-stream-cleanup beat job.
- Stale-offset detection: on first connect, the handler runs `XRANGE tutor:turn:{tid} - + COUNT 1` to check whether the requested `Last-Event-ID` predates the stream's first-retained entry. If so, emit a `trim_detected` event so the client falls back to the `/status` poll path. (See plan-v7 §V7-F4 for the failure mode this prevents — `XREAD` from a trimmed offset silently returns *next* entries, hiding the gap.)

## Alternatives considered

- **Redis pub/sub** — no replay; the use case is exactly disconnect+resume. Rejected.
- **PostgreSQL `LISTEN/NOTIFY` + a `turn_events` table** — would give us durability and replay for free, but Postgres `NOTIFY` payloads cap at ~8 KB and the wake-up latency under load is in the tens-of-ms; SSE wants sub-10ms first-token. Rejected.
- **Kafka / NATS** — both purpose-built for this; both add an entire moving part we don't have on a t4g.small demo deploy. Revisit at scale.
- **In-process queue (asyncio.Queue) + sticky sessions** — would force every replica to handle every turn it originated. Sticky sessions on Caddy + the prospect of losing a turn when a replica restarts mid-stream make this strictly worse than the Redis path.

## Consequences

- **Replay window:** 5 min replay window after `turn_complete`; the orphan-stream cleanup beat job catches forgotten streams at 24 h.
- **Memory:** `MAXLEN ~ 500` per stream caps memory at ~150 KB per active stream. At 100 concurrent turns that's ~15 MB — fine on t4g.small.
- **Last-Event-ID semantics:** Client must send the *entry ID* (`<ms>-<seq>`), not a synthetic event index. The SSE wire encoding already supports this.
- **Operational signal:** `XLEN tutor:turn:{tid}` is the per-turn event count. `XINFO STREAM tutor:turn:{tid}` exposes first-id, last-id, length, max-deleted-id — feeds the admin observability panel.
- **Stale-offset edge case:** must check the first-retained entry before subscribing, otherwise the client sees a clean stream when in fact it's missed half of one. Test enumerated in plan-v7 §V7-F4.
- **Future cluster considerations:** keys all live under the `tutor:turn:` prefix; Redis Cluster slot pinning via hashtag (`{turn-id}`) only matters if we ever shard Redis. Not today.

## References

- [Redis Streams data type intro](https://redis.io/docs/data-types/streams/)
- [SSE spec — `Last-Event-ID` retry semantics](https://html.spec.whatwg.org/multipage/server-sent-events.html#last-event-id)
- plan-v7 §V7-F4 — stale Last-Event-ID after trim
- ADR-0017 — Celery worker pool; producer side of this contract
- ADR-0019 — atomic phase fence + `after_commit` enqueue; turn lifecycle around this stream
