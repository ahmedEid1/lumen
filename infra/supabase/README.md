# Supabase — Lumen Postgres + pgvector

Lumen uses Supabase **only as managed Postgres 17 + pgvector**. We do **not**
use Supabase Auth, Storage, Realtime, Edge Functions, or Studio's migration
UI — those are owned by Lumen's own stack (FastAPI, Cloudflare R2, our
Alembic migrations).

Free tier ceilings to be aware of:

| Resource           | Free-tier cap            | Notes for Lumen                                                                                                                |
|--------------------|--------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| Database size      | 500 MB                   | The biggest consumer is the `lesson_chunks` pgvector table. Pruning unused embeddings is the first knob to turn (see runbook). |
| Egress             | 5 GB / mo                | Negligible at demo traffic; bumps if `pg_dump` backups are pulled regularly.                                                   |
| Connections        | 60 direct / 200 pooled   | Lumen runs through the **session pooler** — see `connection-pooler-note.md`.                                                   |
| Project pause      | 7 days no activity       | Free projects pause after a week idle. The daily-digest GitHub-Actions cron pokes the DB once a day, which keeps it alive.     |

## First-time database setup

After creating the Supabase project but **before** the first Lumen deploy
runs migrations, open *Supabase Studio → SQL Editor* and run the snippet
below. This is the only manual SQL the operator ever has to apply directly;
everything else is managed by Alembic.

```sql
-- 1. Enable pgvector in Supabase's `extensions` schema.
--
-- Supabase ships pgvector pre-installed but does NOT enable it by default.
-- Per Supabase's hardening guidance, extensions live in the `extensions`
-- schema (not `public`) so they don't pollute application namespaces. The
-- `with schema extensions` clause is the Supabase-required form.
create extension if not exists vector with schema extensions;

-- 2. Make the `extensions` schema visible to the application role.
--
-- Lumen's Alembic migration 0017 (apps/backend/alembic/versions/
-- 2026_07_07_0017-0017_pgvector_extension.py) issues
--   CREATE EXTENSION IF NOT EXISTS vector
-- in the default schema. On Supabase that's a no-op (the extension is
-- already enabled in `extensions`), but ORM declarations like
--   Mapped[list[float]] = mapped_column(Vector(384), ...)
-- resolve the `vector` type via the role's search_path. Adding
-- `extensions` to the search_path makes `Vector(...)` resolve cleanly
-- without rewriting the model layer.
alter role postgres in database postgres set search_path = "$user", public, extensions;
alter database postgres set search_path = "$user", public, extensions;
```

Once that's in, the regular Alembic chain (`alembic upgrade head`, which the
Fly api runs as its `release_command`) takes care of every other migration
in order — schema, indexes, the `lesson_chunks` table, the `llm_calls`
audit log (H1), the lot.

## Connection strings

There are three Supabase-issued URLs you need to know:

1. **Direct connection** (`db.<project-ref>.supabase.co:5432`) — the actual
   Postgres host. Used only for one-off psql sessions; **not what Lumen
   connects with**.
2. **Session pooler** (`aws-0-<region>.pooler.supabase.com:5432`) — pgBouncer
   in session mode. This is what Lumen's api + worker use. Compatible with
   SQLAlchemy 2's async pool + prepared statements.
3. **Transaction pooler** (`aws-0-<region>.pooler.supabase.com:6543`) —
   pgBouncer in transaction mode. **DO NOT USE** with Lumen. See
   `connection-pooler-note.md` for the full reasoning.

In Lumen's env contract:

```env
# Note the `+asyncpg` driver for the API/worker async pool.
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres

# And `+psycopg` for the sync path Alembic uses.
DATABASE_URL_SYNC=postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

(Replace `eu-central-1` with whatever region you picked. Use the EU region
that's closest to the Fly `fra` deployment — same continent kills 80 ms of
round-trip per query, which adds up under cold-start.)

URL-encode any non-alphanumerics in the password (Supabase generates
passwords with `@`, `:`, `/`, etc — they must be `%40`/`%3A`/`%2F` in the
URL).

Set these on Fly via:

```bash
flyctl secrets set --app lumen-api \
  DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<pw>@...pooler.supabase.com:5432/postgres' \
  DATABASE_URL_SYNC='postgresql+psycopg://postgres.<ref>:<pw>@...pooler.supabase.com:5432/postgres'

flyctl secrets set --app lumen-worker \
  DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<pw>@...pooler.supabase.com:5432/postgres' \
  DATABASE_URL_SYNC='postgresql+psycopg://postgres.<ref>:<pw>@...pooler.supabase.com:5432/postgres'
```

## Why no Supabase Studio migrations?

Two reasons:

1. **Source of truth conflict.** Alembic in `apps/backend/alembic/versions/`
   is the canonical migration history. If a hand-edited Supabase migration
   diverged from that, we'd have two competing histories — one in code, one
   in the dashboard — and the next `alembic upgrade head` would either fail
   or silently re-apply something already there.
2. **Reproducibility.** Every dev box runs the same Alembic chain. If you
   make a schema change in Supabase Studio it doesn't exist anywhere in the
   repo, so the next developer is stuck.

The one exception is the bootstrap snippet above. We accept that single
manual step because it sets up the extension *infrastructure* (where
extensions live, the role's search_path) — things Alembic can't reliably
manage cross-platform.

## Backups

Supabase's free tier doesn't include scheduled backups. For a portfolio
demo this is acceptable (the seed data can be regenerated on demand via
`make demo-seed`), but if real users start using Lumen the operator should:

- Upgrade to Pro ($25/mo) — adds daily automatic backups.
- Or run `pg_dump` from a GitHub Actions cron against the direct connection
  (port 5432), gzip, and push to R2. Egress stays inside the free tier
  while traffic is light.

See `docs/deployment/free-tier.md` for the cron template.

## Triage cheatsheet

| Symptom                                                  | Likely cause                                                                                                  |
|----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `type "vector" does not exist`                           | Extension not enabled (skipped the SQL snippet above) or `search_path` doesn't include `extensions`.          |
| `prepared statement "..." does not exist`                | You connected via the **transaction** pooler (port 6543) instead of session pooler. See pooler note.          |
| `FATAL: too many connections`                            | Multiple Fly Machines holding pool connections at once during a rolling deploy. Lower `DATABASE_POOL_SIZE`.  |
| Project paused (Supabase emails you)                     | No activity for 7 days. Daily-digest cron should prevent this; check it's green.                              |
| Connection times out from Fly but works from your laptop | Fly's outbound IPs are not allowlisted. Supabase free tier doesn't restrict; double-check the host is right. |
