# Upgrade runbook

Operational checklist for pulling new Lumen code onto an existing
deployment (dev compose stack, staging, or prod). The order matters:
dependency drift between the API and worker containers will surface
as cryptic `ImportError`s inside Celery tasks long after the deploy
appears to have succeeded.

## When `pyproject.toml` changes (new backend deps)

Bare `docker compose up` will keep using the previously built API
image — Docker doesn't auto-rebuild on source changes. After pulling
a commit that touches `apps/backend/pyproject.toml` you need:

```bash
docker compose build api worker beat
docker compose up -d
```

(or `docker compose up --build` to do both in one step.)

The current `apps/backend/Dockerfile` copies `pyproject.toml` and
`uv.lock` into the `deps` stage *before* it copies the source, so
Docker's layer cache is keyed on dependency declarations only.
**Any** change to either of those two files invalidates the install
layer; the resulting rebuild picks up newly added deps automatically.
A code-only change reuses the cached deps layer and rebuilds in
seconds.

The install line itself has a two-pass fallback:

1. `uv sync --frozen --no-install-project --no-dev` — the fast path
   when `uv.lock` is already in sync with `pyproject.toml`. Installs
   the pinned graph in seconds.
2. If a developer added a dep to `pyproject.toml` without re-running
   `uv lock`, `--frozen` refuses to update the lock and exits
   non-zero; the fallback `uv pip install -e '.'` then resolves
   straight from `pyproject.toml` and lays the new dep down.

So a clean rebuild always lands the new deps — you just have to ask
for the rebuild.

### Verifying a worker rebuild picked up the deps

```bash
docker compose exec worker python -c \
  "import pgvector, fsrs, anthropic, openai, pyld, \
youtube_transcript_api, notion_client; print('ok')"
```

All seven of those were added in the Phase E (E0 / E1 / E3 / E4 / E5)
rebuild commits. If any `ImportError`s — the worker container is
still on the pre-rebuild image, run `docker compose build worker`
and bounce.

## When the search service was removed (rebuild Cut A9)

After upgrading past Cut A9 (which deleted the `meilisearch`
service block from `docker-compose.yml`), run
`docker compose down --remove-orphans` once to clear the orphan
Meilisearch container — typically named `lumen-search-1` on a
stack that was up before the cut — left over from the old search
service. `docker compose up` will warn about the orphan but won't
remove it on its own; left running, it'll keep the named volume
hot and fail subsequent `docker volume prune` runs.

Verify the orphan is gone:

```bash
docker compose ps -a | grep -i search   # should print nothing
```

Search now runs entirely on Postgres `tsvector` + GIN for
keyword search and pgvector for semantic retrieval — there's no
external search service to bring back up.

## When the database schema changes

Alembic migrations run automatically on `make migrate` (dev) or
the prod compose stack's API healthcheck loop.

`make migrate` is now **phase-aware** (PR-11 / S7pre.9). It never runs a
blind `alembic upgrade head` — instead it applies only *additive* (phase A)
revisions and **stops at the first release-gated revision** (an IRREVERSIBLE
data-collapse, a metadata-default flip, or a NOT-NULL tighten). When a phase
boundary blocks progress the command exits non-zero and prints the exact
`make migrate.phase` step to run next.

### Phased revisions (DR-12 / two-role rebuild)

Every revision `>= 0030` declares a rollout `PHASE`:

| Phase | Meaning | Example | How it's applied |
|-------|---------|---------|------------------|
| **A** | additive, zero-downtime, safe any deploy | 0030 `users.deleted_at` | `make migrate` / `migrate.safe` (automatic) |
| **B** | IRREVERSIBLE data-collapse, release-gated | 0031 `role_collapse_backfill` | `make migrate.phase ALLOW_PHASE_MIGRATION=1` (explicit) |
| **C** | metadata default flip, narrowed-enum release | 0032 `role_default_user` | `make migrate.phase ALLOW_PHASE_MIGRATION=1` (explicit) |
| **D** | NOT-NULL tighten, evidence-gated | 0043 `lesson_chunks_model_not_null` | `make migrate.phase ALLOW_PHASE_MIGRATION=1` (explicit) |

The two-role role-collapse runbook step-order:

1. **Phase A** (additive, automatic): `make migrate.safe` (or `make migrate`).
   Brings the DB up to the latest additive rev (e.g. 0030); the fleet now
   tolerates the wider role set.
2. **Phase B** (IRREVERSIBLE 0031): once the fleet is fully on the Phase-A
   image, run `make migrate.phase ALLOW_PHASE_MIGRATION=1` to apply the
   `student|instructor → user` data-collapse. **0031 has a no-op downgrade
   (R-C4); rollback is image-rollback, never `alembic downgrade` past 0031.**
3. **Phase C** (0032): with the narrowed-enum + normalization release, run
   `make migrate.phase ALLOW_PHASE_MIGRATION=1` again to flip the column
   `server_default` to `'user'`.

Run **one phase per release** per the deploy runbook; never batch B+C+D.

```bash
# additive only (default):
make migrate                 # == make migrate.safe

# the one explicit phased step for this release:
make migrate.phase ALLOW_PHASE_MIGRATION=1
```

To run them by hand against a deployed stack (bypassing the guard — only when
you have read the phase table above and accept the consequences):

```bash
docker compose exec api alembic upgrade head
```

Always run migrations **before** bouncing the worker — the worker
boots Celery tasks that import ORM models, and a model/table
mismatch on boot will crash the worker before the next migration
window.

## When `docker-compose.yml` changes service shape

Run `docker compose up -d --remove-orphans` so containers whose
service blocks were renamed or deleted are cleaned up in the same
step. See the Cut A9 note above for the most recent example.
