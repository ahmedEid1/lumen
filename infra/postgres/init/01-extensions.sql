-- Lumen — runs on first Postgres boot only (when data dir is empty).
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
-- vector: Phase E0 — semantic search over lesson chunks. Requires
-- the ``pgvector/pgvector:pg17`` image (or any Postgres build with
-- the extension installed at the system level); the alembic
-- migration ``0017_pgvector_extension`` will fail loudly on plain
-- ``postgres:17-alpine``, which is the intended failure mode.
CREATE EXTENSION IF NOT EXISTS "vector";
