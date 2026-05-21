# ADR-0002: PostgreSQL, Redis, MinIO as the data plane

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

The legacy app used SQLite + local filesystem + a single Redis instance for Channels. We need a data plane that supports:

- Relational data with strong constraints and JSON columns for the quiz payload.
- A pub/sub channel so multiple API replicas can fan-out chat messages.
- Object storage for lesson assets that we don't want to push through the Python process.
- A path to managed services (RDS, ElastiCache, S3) without changing code.

## Decision

- **PostgreSQL 17** as the primary store. Use `JSONB` for the polymorphic lesson payload.
- **Redis 7** for caching, Celery broker, rate-limiter token buckets, WS pub/sub, and presence sorted sets.
- **MinIO** in dev/self-hosted, S3 contract in code so any S3-compatible target works in prod.

## Alternatives considered

- **MySQL** — perfectly fine; we prefer Postgres for `JSONB`, full-text, and the `pg_trgm` extension we may use later.
- **NATS instead of Redis for pub/sub** — adds another service for marginal benefit at v1 scale.
- **Local filesystem for uploads** — couples assets to API replicas; not horizontally scalable.

## Consequences

- Dev needs Postgres + Redis + MinIO containers — bundled in Compose.
- Operators who already have managed Postgres/Redis/S3 simply point env vars at them.
- We get full-text search via Meilisearch (next ADR), not Postgres, to keep query latency predictable.

## References

- [PostgreSQL JSONB](https://www.postgresql.org/docs/17/datatype-json.html)
- [MinIO S3 compatibility](https://min.io/docs/minio/linux/developers/python/minio-py.html)
