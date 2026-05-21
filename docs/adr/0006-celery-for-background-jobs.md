# ADR-0006: Celery for background jobs

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

We have asynchronous work that does not belong in the request path: sending emails, processing uploaded media, reindexing search, rendering completion certificates. We need a job queue.

## Decision

Celery 5.x with Redis as the broker and result backend. Beat schedules periodic tasks (sweeps, reindex, daily backups).

## Alternatives considered

- **arq** — clean, async-native. We picked Celery for ecosystem maturity (Flower, retries, chord, dead-letter) and operator familiarity.
- **Dramatiq** — strong contender; Celery edges it on documentation and beat.
- **In-process background tasks** — fine for fire-and-forget logging, not for retries, scheduling, or anything user-visible.

## Consequences

- Two extra services: `worker` and `beat`.
- Tasks must be idempotent (we enforce by convention; tested with property-based retries).
- We avoid hidden ORM access — tasks receive ids and re-fetch within their own session.

## References

- [Celery best practices](https://denibertovic.com/posts/celery-best-practices/)
