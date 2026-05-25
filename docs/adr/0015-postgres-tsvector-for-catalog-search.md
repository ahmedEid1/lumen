# ADR-0015: Postgres `tsvector` for catalog full-text search

- **Status:** Accepted
- **Date:** 2026-05-25
- **Deciders:** @ahmedEid1
- **Supersedes:** [ADR-0003](0003-meilisearch-for-catalog-search.md)

## Context

ADR-0003 picked Meilisearch v1.10 as a dedicated search service for the public course catalog. After running with that decision for the rebuild we hit two costs that didn't pay off at this catalog size:

- **Operational footprint** — second service in `docker-compose.yml`, second healthcheck, second port to expose, second secret to rotate. For a single-VM demo deploy (AWS t4g.small, 2 GB RAM — see `docs/deployment/aws-vps.md`) the marginal RAM was real.
- **Reindex coordination** — the Celery `reindex` task had to keep Meili and Postgres in sync. Every publish/unpublish/delete added a moving piece that could drift.

The catalog itself is small (thousands of rows, not millions). Postgres is already in the stack and already running pgvector for RAG retrieval (the `vector(384)` column lives on `lesson_chunks`, a separate table). Adding a `tsvector` column on `courses` is essentially free — same database, same backup, same connection pool.

## Decision

Drop Meilisearch. Add `courses.search_vector tsvector GENERATED ALWAYS AS (...) STORED` plus a GIN index. Postgres maintains the column on every insert/update — **no Celery trigger needed for course search**. The original Celery `reindex` task survives but it now exclusively rebuilds lesson-chunk embeddings for the RAG tutor (a separate pipeline against the `vector(384)` column).

The `services/search.py` abstraction is gone — there's nothing to swap behind anymore. Search queries go straight from the catalog repository to a single SQL statement (`SELECT ... WHERE search_vector @@ websearch_to_tsquery(:q)` plus filters).

## Consequences

- **Wins**: one fewer container, one fewer healthcheck, one fewer reindex code path, lower RAM ceiling on the demo VM, zero drift between catalog rows and their search index (Postgres guarantees the column is always current).
- **Losses**: no typo tolerance (Meili's headline feature). The repository code (`apps/backend/app/repositories/courses.py:140-170`) handles partial-word matches via an ILIKE-OR-branch — `websearch_to_tsquery @@ search_vector OR title ILIKE '%q%' OR overview ILIKE '%q%'`, ranked at `ts_rank` for FTS hits and `0.0` for ILIKE-only — so "java" still finds "javascript" that the English stemmer would otherwise miss. If typo tolerance matters later we'll revisit (`pg_trgm` is the natural next step before reaching for Meili again).
- **Migration impact**: the `MEILI_*` env vars are dropped from `Settings` and `.env.example`; any test fixture that still calls `monkeypatch.setenv("SEARCH_BACKEND", "postgres")` is a harmless no-op (Settings has no such field and `extra="ignore"` swallows it).

## Alternatives reconsidered

The ADR-0003 alternatives still apply. Postgres `tsvector` + `pg_trgm` was the runner-up in 2026-05-21 ("capable, but slower on typo tolerance"); after running with Meili we judged that the typo-tolerance gap doesn't matter at our scale.

## Status

Implemented. See `apps/backend/app/repositories/courses.py` (the actual query), `apps/backend/alembic/versions/2026_07_05_0014-0014_courses_search_vector.py` (the column + GIN index), and `CHANGELOG.md` `[Unreleased]` "Scrubbed Meilisearch fossils" entry.
