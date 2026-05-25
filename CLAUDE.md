# CLAUDE.md

Project-specific guidance for Claude Code agents. Read this once at the start of a session, then trust the source.

## What this project is

**Lumen** is a 2026 rewrite of an old Django e-learning prototype. The new stack is:

- **Backend:** Python 3.13, FastAPI, async SQLAlchemy 2, Alembic, Celery, structlog
- **Frontend:** Next.js 15 (App Router, RSC), React 19, TypeScript 5, Tailwind 4, shadcn-style primitives, TanStack Query
- **Data:** PostgreSQL 17 (with `pgvector` + `tsvector` full-text search), Redis 7, MinIO (S3-compatible)
- **Delivery:** Docker Compose (dev + prod), GitHub Actions CI/CD, Trivy + CodeQL + gitleaks

The original Django prototype lived under `legacy/` through v1.0.0 as a read-only archive; it was deleted in May 2026 once the rewrite shipped and the snapshot stopped earning its 160 MB. The reference history is preserved in git — `git log -- legacy/` recovers the tree at any pre-deletion commit if you need it.

## Layout

```
apps/backend/      FastAPI service (app/, alembic/, tests/, pyproject.toml)
apps/frontend/     Next.js app (src/app, src/components, src/lib, tests/)
docs/              PRD, architecture, ADRs, SDLC, security, deployment, runbooks
infra/             Caddy, Postgres init scripts, Prometheus config
.github/           CI workflows, issue/PR templates, CODEOWNERS, dependabot
docker-compose.yml docker-compose.prod.yml
Makefile           make up | down | migrate | seed | test | lint | fmt | ...
```

Within the backend:

- `app/api/v1/` — thin HTTP handlers; one module per resource
- `app/services/` — business logic; the only place invariants live
- `app/repositories/` — async SQLAlchemy data access; no HTTP concerns
- `app/schemas/` — Pydantic v2 DTOs
- `app/models/` — SQLAlchemy ORM models (also re-exported in `__init__.py`)
- `app/workers/` — Celery app and tasks
- `app/core/` — config, logging, security, errors, ids, ratelimit
- `app/db/` — engine + session factory

## Conventions

- **IDs** are 21-char `nanoid` opaque strings — never expose integers in URLs
- **Response envelope on errors** is `{ "error": { code, message, details, request_id } }` — use `AppError` subclasses (`NotFoundError`, `ConflictError`, etc.) from `app.core.errors`
- **Times** are `DateTime(timezone=True)` everywhere; ISO 8601 UTC in JSON
- **Soft-delete** with `deleted_at` for user-visible content (Course, Lesson, Review); hard-delete for sessions, refresh tokens, ephemeral data
- **Mutating endpoints** that may be safely retried accept `Idempotency-Key` — not yet enforced in v1 but planned
- **Auth** is JWT access (15 min) + rotating opaque refresh (14 d). Cookies for browsers (`__Host-*` in prod), Bearer for API clients, `?token=` for WebSockets
- **Roles** are `student | instructor | admin` — checked in the service layer, not just routes
- **Pagination** is offset+page for catalog-style reads; cursor for messages/audit
- **Pydantic v2** — use `model_validate`, `model_dump(mode="json")`, `ConfigDict(from_attributes=True)`

## Commands

```bash
make up                            # bring the full dev stack up
make migrate                       # alembic upgrade head
make revision m="..."              # alembic autogenerate
make seed                          # demo data (admin/teacher/student)
make test                          # backend + frontend
make test.api                      # backend only
make test.web                      # frontend unit only
make lint / make fmt
make shell.api / make shell.web / make shell.db
make openapi                       # dump apps/backend/openapi.json (in-container)
make openapi.local                 # same but on the host (needs local deps)
make api-client                    # regenerate the TS client from OpenAPI
```

Default seeded accounts (dev only):

| Role       | Email              | Password    |
|------------|--------------------|-------------|
| Admin      | admin@lumen.test   | Admin!2026  |
| Instructor | teacher@lumen.test | Teach!2026  |
| Student    | student@lumen.test | Learn!2026  |

## How to make changes safely

1. **Read the relevant ADR first** (`docs/adr/`). If you're changing an architectural seam, add a new ADR.
2. **Test first**, especially around auth, RBAC, and money-adjacent paths. Backend tests run against a real Postgres + Redis (no mocks).
3. **One topic per commit**; Conventional Commits subject; squash on merge.
4. **CHANGELOG entry** for user-visible changes.
5. **OpenAPI is the contract** — when you add/change an endpoint, regenerate the TS client (`make api-client`) if you ship code that consumes it.

## Testing notes

- Backend `conftest.py` creates a transient DB per session, force-clears the Settings cache after env-var overrides, and exposes `make_user`/`auth_headers` fixtures
- Search uses Postgres `tsvector` (no separate search service); the legacy `SEARCH_BACKEND` env var is a no-op on current `Settings` but is still set in a couple of test fixtures for historical reasons
- Frontend tests use Vitest + happy-dom; E2E uses Playwright with the dev compose stack

## Gotchas

- **Module reorder uses a two-phase update** (negative tmp values then targets) to avoid the `uq_modules_course_order` constraint
- **Refresh-token reuse triggers full chain revocation** — by design; covered in `test_refresh_rotates_and_reuse_detection`
- **Celery is best-effort in dev** — `_schedule_index` and the password-reset email both swallow broker errors so the API stays up without a worker
- **Compose env on Windows hosts** logs CRLF warnings on `git add` — harmless; `.gitattributes` would silence it but isn't worth the churn
- **Pydantic v2 + SQLAlchemy 2** — keep models and schemas separate; never expose an ORM object as a response without `UserPublic.model_validate(...)` or similar
- **Search index** lives in a Postgres `tsvector` column; the Celery reindex task fires on publish/unpublish/delete and rebuilds the row's vector. There's no separate search service — the original Meilisearch wire was retired during the rebuild.

## Where to put new things

- **New endpoint** → handler in `app/api/v1/<resource>.py`, service in `app/services/`, repo in `app/repositories/`, schema in `app/schemas/`, register in `app/api/router.py`
- **New table** → model in `app/models/<name>.py`, add to `app/models/__init__.py`, then `make revision m="add ..."` and review the generated migration
- **New UI route** → `apps/frontend/src/app/<route>/page.tsx`, components in `src/components/<area>/`, data hooks via TanStack Query with keys in `src/lib/query/keys.ts`
- **New ADR** → copy `docs/adr/0000-template.md`, bump the number, add to PR description

## What to leave alone

- `.claude/ralph-loop.local.md` (loop state — read-only signal)
- Anything under `infra/` without a corresponding ADR change
