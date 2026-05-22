# Supabase pooler — session vs transaction mode

Supabase fronts every project's Postgres with two pgBouncer endpoints:

| Endpoint            | Port | pgBouncer mode | Use with Lumen?        |
|---------------------|------|----------------|------------------------|
| `pooler.supabase.com` | 5432 | **session**    | **Yes** — this is the one. |
| `pooler.supabase.com` | 6543 | **transaction**| **No** — incompatible.     |

This note explains why, so the next operator who sees the same blog post or
Supabase quickstart doesn't switch us to the transaction pooler "for
performance" and break the api.

## TL;DR

- Lumen runs SQLAlchemy 2 with the async (`asyncpg`) driver. asyncpg uses
  **prepared statements** for every parameterised query — that's how
  `$1, $2, $3` placeholders get turned into a query plan and re-used.
- Transaction-mode pgBouncer multiplexes statements across many backend
  connections inside a single client connection. A prepared statement
  registered on backend A is invisible to backend B, so the next reuse of
  the same statement blows up with `prepared statement "__asyncpg_stmt_1__"
  does not exist`.
- Session-mode pgBouncer pins one backend per client connection for the
  lifetime of the client's session, so prepared statements stay valid.
- The cost: session mode doesn't multiplex, so you get fewer effective
  connections per Supabase pool slot. At Lumen's idle / demo traffic this
  is irrelevant. At real production scale, the answer is to disable
  statement caching (asyncpg's `statement_cache_size=0`) or move to
  Supavisor — not to flip the pooler mode.

## What that looks like in the connection string

```env
# Right (session pooler, port 5432):
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres

# Wrong (transaction pooler, port 6543):
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

Symptom of the wrong one: the api boots fine, the first request hits the
DB and returns, the *second* request 500s with:

```
asyncpg.exceptions.InvalidSQLStatementNameError:
  prepared statement "__asyncpg_stmt_1__" does not exist
```

This is the *single most common* footgun when moving Lumen onto Supabase.
If you see it: check the port.

## What about Alembic migrations?

Alembic uses the **sync** driver (`+psycopg`) and runs short-lived
transactions. Either pooler mode would work for migrations specifically.
We still send Alembic through the session pooler (5432) so we don't have
to remember "this URL uses one port, that URL uses another" — one host,
one port, one mental model.

## What if I really want transaction-mode performance?

Don't, until you have real evidence of a connection bottleneck. The path
to take then is:

1. Move to **Supavisor** (Supabase's newer pooler, transaction-safe with
   asyncpg via the `statement_cache_size=0` knob). It's already what
   Supabase's dashboard nudges users toward for serverless workloads.
2. Or, keep session-mode pgBouncer but raise the `[pool_size]` knob on
   Supabase Pro. Still cheaper than the engineering cost of debugging
   "prepared statement does not exist" at 3 AM.

## See also

- Supabase docs: <https://supabase.com/docs/guides/database/connecting-to-postgres>
- asyncpg + pgBouncer compatibility note: <https://magicstack.github.io/asyncpg/current/faq.html#why-am-i-getting-prepared-statement-errors>
- Lumen's own engine factory: `apps/backend/app/db/base.py` (uses
  `pool_pre_ping=True` and a small pool size by default — friendly to
  pgBouncer's session limits).
