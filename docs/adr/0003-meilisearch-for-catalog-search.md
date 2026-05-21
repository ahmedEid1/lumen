# ADR-0003: Meilisearch for catalog full-text search

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

We need fuzzy, typo-tolerant search over the public course catalog (title, overview, instructor name, tags, subject). The catalog is small (thousands, not millions) but we want a fast, dedicated query path that won't be slowed by other workloads on Postgres.

## Decision

Run Meilisearch v1.10 as a dedicated service. Index `courses` on publish/unpublish; reindex via a Celery task. Search requests go straight from the API to Meilisearch; the frontend never talks to it directly (we don't ship a tenant key to the browser at v1).

## Alternatives considered

- **Postgres `tsvector` + `pg_trgm`** — capable, but slower on typo tolerance and harder to tune. Reasonable fallback if the operator wants one fewer service; we leave the abstraction in `services/search.py` to swap backends.
- **OpenSearch / Elasticsearch** — heavyweight for our size; operational burden high.
- **Algolia / managed** — fine, costs money, leaks data to a third party.

## Consequences

- One more container in Compose.
- An async reindex pipeline (Celery) we need to keep healthy.
- Operators may set `SEARCH_BACKEND=postgres` to fall back to a `tsvector`-based implementation.

## References

- [Meilisearch docs](https://www.meilisearch.com/docs)
