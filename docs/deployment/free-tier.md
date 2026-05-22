# Free-tier deploy — Lumen live demo

This is the operator runbook for the **Lumen v2 H4 free-tier deployment**.

The target shape is *zero dollars at idle, low-friction first-deploy*:

| Service            | Provider     | Free-tier ceiling                                                | What lives there                                                                                   |
|--------------------|--------------|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| Next.js frontend   | Vercel       | Hobby tier; ~100 GB/mo bandwidth; unlimited deploys                | `apps/frontend/` — RSC pages, public assets, the auth + dashboard + catalog surface                |
| FastAPI api        | Fly.io       | 3 × shared-cpu-1x 256 MB Machines free; scale-to-zero             | `apps/backend/` — REST + WebSocket api, runs Alembic on deploy                                     |
| Celery worker      | Fly.io       | (same allowance)                                                  | Same image as api, runs `celery worker`; scaled to zero, started by GitHub Actions cron once a day |
| Postgres 17 + pgvector | Supabase | 500 MB DB, 5 GB/mo egress, 60/200 connections                     | Lumen's only source of truth — user accounts, course content, embeddings, LLM call audit log       |
| Redis              | Upstash      | 10k commands/day, 256 MB                                          | Celery broker + result backend + slowapi rate-limit counters                                       |
| Object storage     | Cloudflare R2 | 10 GB storage, 1M class-A ops/mo, **0 egress fees**              | User-uploaded course assets (cover images, future video transcodes)                                |
| CI / cron          | GitHub Actions | Generous on public repos                                         | Existing CI, the deploy workflow, the daily-digest cron                                            |
| LLM (H1)           | Groq         | Free-tier rate-limited Llama 3.3 70B                              | All AI features — tutor, authoring, eval-as-judge                                                  |

Steady-state cost at zero traffic: **$0/mo**. The first paid surface you'll
hit is Supabase if `lesson_chunks` (pgvector embeddings) bloats past 500 MB,
or Vercel if your demo goes viral.

> **Loom screencast:** `<TODO operator — drop the 90-second demo URL here once recorded>`

---

## 1. First deploy

This is a one-time setup. Budget ~45 minutes the first time, ~15 each time
after.

### 1.1 Create accounts

Sign up for all five if you don't have them already:

1. **Vercel** — <https://vercel.com/signup>. Hobby plan. Connect GitHub.
2. **Fly.io** — <https://fly.io/app/sign-up>. The free allowance kicks in
   on a non-paid account; you'll be prompted to add a card after the first
   `flyctl auth signup` but won't be charged until you exceed the
   allowance. Install the CLI:

   ```bash
   curl -L https://fly.io/install.sh | sh
   flyctl auth signup        # or: flyctl auth login
   ```

3. **Supabase** — <https://supabase.com/dashboard/sign-up>. Free project,
   pick the region closest to Fly's `fra` (e.g. `eu-central-1`).
4. **Upstash** — <https://console.upstash.com>. Create a Redis database in
   the same EU region.
5. **Cloudflare R2** — <https://dash.cloudflare.com/sign-up>. Enable R2 in
   the dashboard (one-click; no card required for the free tier).

### 1.2 Provision the data services

#### Supabase

1. Create a new project (region: `eu-central-1`, password: long random,
   save it to a password manager).
2. *SQL Editor → New query* → paste and run the snippet from
   `infra/supabase/README.md` (enables `pgvector` in the `extensions`
   schema and updates the role's `search_path`). This is the **only**
   manual SQL step ever required.
3. *Project Settings → Database → Connection String* → copy the **Session
   pooler** URL (port **5432**, NOT 6543 — see
   `infra/supabase/connection-pooler-note.md` for the gory details on why
   transaction-mode pgBouncer breaks asyncpg). You'll need two flavours:

   - Async (for the API + worker):
     `postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`
   - Sync (for Alembic):
     `postgresql+psycopg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`

   URL-encode any special characters in the password (`@` → `%40`, `:` → `%3A`).

#### Upstash Redis

1. Create a Redis database (region: closest to Fly `fra`, eviction:
   `allkeys-lru` is a sensible default for the rate-limit traffic).
2. *Details → REST API → Endpoint and Password* — but Lumen uses the
   plain Redis protocol, not REST. Switch to *Details → Connect → Redis
   URL* and copy the `rediss://default:<password>@<host>:<port>` form.
3. Plan: stick with the free tier. The 10k commands/day ceiling translates
   roughly to ~10k API requests/day if each one bumps a rate-limit
   counter (more with caching). If you trip it, see
   [§5 Cost watch](#5-cost-watch).

#### Cloudflare R2

1. *R2 → Create bucket* → name `lumen-assets`. Location hint: EU.
2. *R2 → Manage R2 API Tokens → Create API Token* → scope to *Object Read
   & Write* on the `lumen-assets` bucket. Copy the *Access Key ID* and
   *Secret Access Key*. Note the *Endpoint* — it looks like
   `https://<account-id>.r2.cloudflarestorage.com`.
3. (Optional) *Bucket → Settings → Public access* — connect a custom
   subdomain for public asset URLs. Without one, presigned URLs work
   fine but assets aren't browseable.

### 1.3 Create the Fly apps

From the repo root (you only do this once per Fly app):

```bash
flyctl apps create lumen-api --org personal
flyctl apps create lumen-worker --org personal
```

> If those names are taken on Fly's global namespace, pick alternates and
> update `infra/fly/fly.api.toml` and `infra/fly/fly.worker.toml`
> accordingly.

### 1.4 Set Fly secrets

Lumen reads every credential from env vars. Set them via `flyctl secrets
set` (which restarts the Machine, so it picks up the new values on the
next request). Copy this template, fill in the values, paste:

```bash
# --- shared (api + worker) ---
read -p "Set these on BOTH lumen-api AND lumen-worker. Press enter."

# Long random — `python -c "import secrets; print(secrets.token_urlsafe(48))"`
SECRET_KEY="..."
JWT_SECRET="..."

DATABASE_URL="postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
DATABASE_URL_SYNC="postgresql+psycopg://postgres.<ref>:<pw>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"

REDIS_URL="rediss://default:<password>@<host>:<port>"
CELERY_BROKER_URL="rediss://default:<password>@<host>:<port>/1"
CELERY_RESULT_BACKEND="rediss://default:<password>@<host>:<port>/2"

# Cloudflare R2 — S3-compatible
S3_ENDPOINT_URL="https://<account-id>.r2.cloudflarestorage.com"
S3_PUBLIC_BASE_URL="https://<your-public-cdn-host>"   # custom domain, or
                                                      # the lumen-assets.r2.dev autoroute
S3_REGION="auto"                                      # R2 ignores this; "auto" is the convention
S3_BUCKET="lumen-assets"
S3_ACCESS_KEY_ID="..."
S3_SECRET_ACCESS_KEY="..."
S3_FORCE_PATH_STYLE="true"

# LLM — Groq Llama 3.3 70B free tier (matches the v2 spec §8 addendum)
OPENAI_API_KEY="<groq-api-key>"
LLM_MAX_TOKENS="1024"

# Email — pick one (only one of these blocks is needed)
#  Option A: Resend (https://resend.com — free tier 100 emails/day)
SMTP_HOST="smtp.resend.com"
SMTP_PORT="465"
SMTP_USERNAME="resend"
SMTP_PASSWORD="<resend-api-key>"
SMTP_FROM="Lumen <demo@your-domain.com>"
SMTP_TLS="true"

# Optional but recommended
SENTRY_DSN=""                # leave empty until you set up Sentry
BADGES_ISSUER_URL="https://lumen-api.fly.dev"
WEB_BASE_URL="https://lumen.vercel.app"

# --- now apply ---
flyctl secrets set --app lumen-api \
  SECRET_KEY="$SECRET_KEY" JWT_SECRET="$JWT_SECRET" \
  DATABASE_URL="$DATABASE_URL" DATABASE_URL_SYNC="$DATABASE_URL_SYNC" \
  REDIS_URL="$REDIS_URL" CELERY_BROKER_URL="$CELERY_BROKER_URL" CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
  S3_ENDPOINT_URL="$S3_ENDPOINT_URL" S3_PUBLIC_BASE_URL="$S3_PUBLIC_BASE_URL" S3_REGION="$S3_REGION" \
  S3_BUCKET="$S3_BUCKET" S3_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" S3_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
  S3_FORCE_PATH_STYLE="$S3_FORCE_PATH_STYLE" \
  OPENAI_API_KEY="$OPENAI_API_KEY" LLM_MAX_TOKENS="$LLM_MAX_TOKENS" \
  SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" SMTP_USERNAME="$SMTP_USERNAME" \
  SMTP_PASSWORD="$SMTP_PASSWORD" SMTP_FROM="$SMTP_FROM" SMTP_TLS="$SMTP_TLS" \
  BADGES_ISSUER_URL="$BADGES_ISSUER_URL" WEB_BASE_URL="$WEB_BASE_URL"

flyctl secrets set --app lumen-worker \
  SECRET_KEY="$SECRET_KEY" JWT_SECRET="$JWT_SECRET" \
  DATABASE_URL="$DATABASE_URL" DATABASE_URL_SYNC="$DATABASE_URL_SYNC" \
  REDIS_URL="$REDIS_URL" CELERY_BROKER_URL="$CELERY_BROKER_URL" CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
  S3_ENDPOINT_URL="$S3_ENDPOINT_URL" S3_PUBLIC_BASE_URL="$S3_PUBLIC_BASE_URL" S3_REGION="$S3_REGION" \
  S3_BUCKET="$S3_BUCKET" S3_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID" S3_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY" \
  S3_FORCE_PATH_STYLE="$S3_FORCE_PATH_STYLE" \
  OPENAI_API_KEY="$OPENAI_API_KEY" LLM_MAX_TOKENS="$LLM_MAX_TOKENS" \
  SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" SMTP_USERNAME="$SMTP_USERNAME" \
  SMTP_PASSWORD="$SMTP_PASSWORD" SMTP_FROM="$SMTP_FROM" SMTP_TLS="$SMTP_TLS" \
  BADGES_ISSUER_URL="$BADGES_ISSUER_URL" WEB_BASE_URL="$WEB_BASE_URL"
```

Confirm:

```bash
flyctl secrets list --app lumen-api
flyctl secrets list --app lumen-worker
```

You should see ~25 secrets per app. None of the *values* are visible —
just digests — which is the right behaviour.

### 1.5 First Fly deploy

```bash
flyctl deploy --config infra/fly/fly.api.toml \
              --dockerfile infra/fly/Dockerfile.fly --remote-only

flyctl deploy --config infra/fly/fly.worker.toml \
              --dockerfile infra/fly/Dockerfile.fly --remote-only
```

The api deploy runs `alembic upgrade head` as its `release_command`
before the new Machines accept traffic — first deploy will install every
migration including pgvector setup. Watch the log for the migration
output and any `ERROR` line.

### 1.6 Bootstrap the demo data

Run the base seed + the demo bundle once. We do this via `flyctl ssh
console -C` so the commands execute inside the api Machine (which has the
correct env + a Python interpreter):

```bash
flyctl ssh console --app lumen-api --command "python -m app.cli seed"
flyctl ssh console --app lumen-api --command "python -m app.cli demo-seed"
flyctl ssh console --app lumen-api --command "python -m app.cli reindex"
```

After this you should be able to hit:

```bash
curl https://lumen-api.fly.dev/api/v1/health/live    # → {"status":"ok"}
curl https://lumen-api.fly.dev/api/v1/health/ready   # → {"status":"ok","checks":{...}}
curl https://lumen-api.fly.dev/api/v1/catalog/courses
```

…and the catalog response should list the three demo courses.

### 1.7 Import the repo on Vercel

Follow `infra/vercel/README.md` step-by-step. After the first Vercel
deploy lands, open `https://lumen.vercel.app` (or your custom domain) —
the catalog page should load and the demo learner login should work:

- Email: `demo@lumen.test`
- Password: `Demo!2026`

### 1.8 Wire the GitHub Actions secrets

1. Repo *Settings → Secrets and variables → Actions → New repository
   secret*:
   - `FLY_API_TOKEN`. Get the value via:
     ```bash
     flyctl tokens create org   # org-wide, simplest
     # or, scoped tighter:
     flyctl tokens create deploy --app lumen-api
     ```
2. The `Deploy` and `Daily digest` workflows now have what they need.
   The next push to `Rewrite` after CI passes will trigger an auto-deploy.

---

## 2. Day-2 operations

### Rolling back a Fly deploy

`flyctl` keeps every release; `releases` lists them, `releases revert`
re-deploys the previous image.

```bash
flyctl releases --app lumen-api
flyctl releases revert --app lumen-api      # → previous version
```

Rolling back the api will not re-run migrations (good — Alembic
downgrade is a manual decision). If the bad release also shipped a
migration, you have two paths:

- **The migration was forward-compatible** (added nullable columns,
  optional indexes): the rollback is safe; the new column just sits
  unused.
- **The migration broke an invariant**: you'll need to `alembic
  downgrade -1` manually before the rolled-back code starts:
  ```bash
  flyctl ssh console --app lumen-api --command "alembic downgrade -1"
  flyctl releases revert --app lumen-api
  ```

### Rotating a secret

```bash
# Generate the new value, then:
flyctl secrets set --app lumen-api ANTHROPIC_API_KEY="<new-key>"
# Fly restarts the Machine automatically. Confirm:
flyctl logs --app lumen-api | grep -i "starting"
```

For `JWT_SECRET` rotation specifically: rotating invalidates every
access + refresh token in flight. Plan for a brief "log in again" event
across all sessions, or set a `JWT_SECRET_PREVIOUS` and teach the auth
service to accept either for the rotation window (not yet implemented
in v1).

### Checking the daily-digest workflow

`https://github.com/<owner>/<repo>/actions/workflows/daily-digest.yml`

Every run logs the `flyctl ssh console` output. If a run is red, the
most common causes are:

1. The worker Machine couldn't auto-start — check `flyctl status --app
   lumen-worker`. A missing secret often shows up here.
2. The Celery broker is unreachable — Upstash maintenance or you tripped
   the 10k/day quota. Upstash UI → metrics tab.
3. The `digest` task itself failed — `flyctl logs --app lumen-worker`
   for the structlog trace.

To run the digest manually right now:

```bash
gh workflow run daily-digest.yml --ref Rewrite
```

…or, without the GH CLI: Actions tab → Daily digest → Run workflow.

### Reseeding the demo data

The H4 seed is idempotent; safe to re-run any time. After a fresh
Supabase project or a `DROP SCHEMA public CASCADE` mishap:

```bash
flyctl ssh console --app lumen-api --command "python -m app.cli seed"
flyctl ssh console --app lumen-api --command "python -m app.cli demo-seed"
flyctl ssh console --app lumen-api --command "python -m app.cli reindex"
```

Locally, `make demo-seed` does the same against the dev compose stack.

### Tail logs

```bash
flyctl logs --app lumen-api      # api
flyctl logs --app lumen-worker   # worker
```

For Vercel, the dashboard's *Logs* tab is the equivalent. For Supabase,
*Project → Logs → Postgres* shows query-level traces (useful when
chasing N+1 surprises).

---

## 3. Cost watch

Where each free tier dies, and what to do.

### Supabase (Postgres + pgvector)

| Trip                              | Symptom                                              | First move                                                                                                       |
|-----------------------------------|------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| 500 MB database size              | Supabase email: "approaching limit"                  | Run `select pg_size_pretty(pg_total_relation_size('lesson_chunks'));` — embeddings are usually the biggest table. |
| 60 direct connections             | `FATAL: too many connections`                        | Lower `DATABASE_POOL_SIZE` on Fly secrets (default 10 → 5 is fine on this traffic). Restart api.                  |
| 7-day inactivity pause            | UI shows project paused                              | The daily-digest cron should prevent this. Verify the workflow has been green for the last 7 days.                |

To prune embeddings: drop chunks for unpublished or deleted courses.
Lesson chunks for archived courses can be safely deleted because the
RAG retrieval never touches them; the worker re-indexes on the next
publish.

```sql
delete from lesson_chunks where lesson_id in (
  select l.id
  from lessons l
  join modules m on m.id = l.module_id
  join courses c on c.id = m.course_id
  where c.deleted_at is not null or c.status != 'published'
);
```

If pruning isn't enough, **upgrade Supabase Pro** ($25/mo). That gets
you 8 GB DB, daily backups, and removes the 7-day pause.

### Upstash (Redis)

| Trip                        | Symptom                                       | First move                                                                                                              |
|-----------------------------|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| 10k commands/day            | 429 from Upstash → api 500s on rate-limit ops | Bump cache TTLs (catalog query, course detail) from 60 s → 5 min. Costs nothing.                                        |
| 256 MB memory               | Upstash UI: usage > 80%                       | Set Celery result expiry: `CELERY_RESULT_EXPIRES=3600` on Fly secrets (default infinite → 1 hour). Restart api + worker. |

If neither helps, **upgrade Upstash Pay-as-you-go** — the first paid tier
is fractional cents per 100k commands and lifts the quota.

### Vercel (Frontend)

| Trip                          | Symptom                                  | First move                                                                                                |
|-------------------------------|------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| 100 GB/mo bandwidth           | Vercel email warning                     | Add `Cache-Control: public, max-age=31536000, immutable` headers to `_next/static/*` (already on by default). |
| Edge requests cap             | Same                                     | Move public catalog pages to RSC + ISR with longer revalidate windows. Same SLO, fewer rebuilds.          |
| Hobby commercial-use TOS bump | Vercel asks you to upgrade               | If the demo earns real money, upgrade to Pro ($20/mo). Until then, Hobby is fine for a portfolio demo.    |

### Fly.io

| Trip                                          | Symptom                                                | First move                                                                                                                 |
|-----------------------------------------------|--------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| 3 × shared-cpu-1x 256 MB free Machines        | Billing email                                          | The api + worker = 2 Machines. Don't run a third 24/7. Use `flyctl scale count 1` everywhere.                              |
| Cold-start latency hurts demo first impression| First request after idle takes ~3 s                    | Set `min_machines_running = 1` on `fly.api.toml` *only* (worker can stay at 0). Costs ~$2/mo per persistent Machine.        |
| Outbound data transfer                        | Mostly free up to 100 GB/mo per region (excluding LLM) | LLM upstream traffic to Groq is included in Fly's free egress. Static asset traffic goes via Vercel/R2, not Fly.            |

### Cloudflare R2

The free tier is unusually generous — **0 egress fees, ever**. The trip
points are 10 GB storage and 1M class-A ops/mo (writes + lists). At
demo traffic neither matters; you'd have to be uploading dozens of
GB-scale assets.

### Groq (LLM)

Free tier is rate-limited, not quota-limited per dollar. Practical caps
(as of writing — Groq updates them):

- Llama 3.3 70B versatile: 30 requests / minute, 6000 tokens / minute,
  ~14k tokens / day per account.

Lumen's H1 LLMCostMeter throttles per-user before Groq does. When a
request hits Groq's RPM ceiling, the api returns the friendly "cool
down" response automatically (see `app/services/llm.py`). The eval
suite (H2) doesn't use the same RPM window so it can still run after
the user-facing surface throttles.

If you need higher capacity:

- Same code path, swap to OpenAI: set `OPENAI_API_BASE=https://api.openai.com/v1`,
  set `OPENAI_API_KEY=<openai-key>`, set `LLM_MODEL=gpt-4o-mini` — done.
- Or swap to Anthropic: set `LLM_PROVIDER=anthropic`, set
  `ANTHROPIC_API_KEY=<key>`, set `LLM_MODEL=claude-sonnet-4-6`.

The provider abstraction is the entire point of H1; this is the
swap-the-LLM moment.

---

## 4. The 90-second Loom

The v2 spec calls for a Loom screencast. Workflow:

1. Open the demo URL in an incognito window.
2. Walk through, in order: catalog → enrol → start a lesson → take the
   quiz → open the AI tutor → ask "explain how AsyncSession differs
   from Session" → expand the trace.
3. Record at 1080p or higher, voiceover on, ~90 seconds.
4. Loom → share → public link, no password.
5. Replace the `TODO operator` line at the top of this doc with the link.
6. Same link goes in the README intro and on the LinkedIn featured tile.

---

## 5. See also

- `infra/fly/fly.api.toml` / `infra/fly/fly.worker.toml` — service config
- `infra/vercel/README.md` — frontend deploy specifics
- `infra/supabase/README.md` — Postgres + pgvector setup
- `infra/supabase/connection-pooler-note.md` — why we use port 5432
- `.github/workflows/deploy.yml` — auto-deploy on `Rewrite` after CI
- `.github/workflows/daily-digest.yml` — Celery beat replacement
- `apps/backend/app/seeds/demo.py` — what the demo seed loads
- `docs/security.md` — the H6 security posture this deploy assumes
- `docs/superpowers/specs/2026-05-22-lumen-v2-agentic-positioning.md`
  §8 — the spec addendum that picked this stack
