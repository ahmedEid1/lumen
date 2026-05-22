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
service from `docker-compose.yml`), run
`docker compose down --remove-orphans` once to clear the orphan
Meilisearch container left over from the old search service.
`docker compose up` will warn about the orphan but won't remove
it on its own; left running, it'll keep the named volume hot and
fail subsequent `docker volume prune` runs.

## When the database schema changes

Alembic migrations run automatically on `make migrate` (dev) or
the prod compose stack's API healthcheck loop. To run them by
hand against a deployed stack:

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
