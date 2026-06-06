# CLAUDE.md

Project-specific guidance for Claude Code agents. Read this once at the start of a session, then trust the source.

## What this project is

**Lumen** is a 2026 rewrite of an old Django e-learning prototype. The new stack is:

- **Backend:** Python 3.13, FastAPI, async SQLAlchemy 2, Alembic, Celery, structlog
- **Frontend:** Next.js 15 (App Router, RSC), React 19, TypeScript 5, Tailwind 4, shadcn-style primitives, TanStack Query
- **Data:** PostgreSQL 17 (with `pgvector` + `tsvector` full-text search), Redis 7, MinIO (S3-compatible)
- **Delivery:** Docker Compose (dev + prod), GitHub Actions CI/CD, Trivy + CodeQL + gitleaks

What makes it more than a CRUD LMS — the **agentic layer** is the centerpiece (Lumen is a portfolio anchor for agentic-AI work):

- **Custom multi-agent orchestrator (no LangChain)** drives the RAG tutor and AI authoring. LLM via Groq Llama 3.3 70B over an OpenAI-compatible client (`app/services/llm.py`); retrieval embeddings via Cloudflare Workers AI into the `pgvector` store.
- **RAG tutor with citations** — course-scoped retrieval; tutor subagents in `app/services/tutor_subagents/` (retriever, concept_explainer, quiz_generator, code_runner, web_searcher).
- **AI authoring + multi-modal ingest** — brief→outline→lessons→quizzes and URL→draft course; `authoring_orchestrator` + `authoring_subagents/`; nothing auto-persists (instructor reviews before commit).
- **MCP server** (`app/mcp/`) exposes Lumen tools to external agents; listed in the public MCP registry.
- **Eval harness** (`app/evals/`) — golden datasets + LLM-as-judge + adversarial probes; `make eval`, public results under `/eval`.
- **Observable agent traces** — every LLM call logged with tokens/cost/latency (`app/services/agent_tracer.py`, `llm_call_log.py`).

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
- `app/services/` — business logic; the only place invariants live (also holds the AI orchestrators + `authoring_subagents/` / `tutor_subagents/` pools)
- `app/repositories/` — async SQLAlchemy data access; no HTTP concerns
- `app/schemas/` — Pydantic v2 DTOs
- `app/models/` — SQLAlchemy ORM models (also re-exported in `__init__.py`)
- `app/workers/` — Celery app and tasks
- `app/core/` — config, logging, security, errors, ids, ratelimit
- `app/db/` — engine + session factory
- `app/evals/` — eval harness: golden/adversarial datasets, LLM-as-judge, runner (`python -m app.evals run`)
- `app/mcp/` — MCP server (`python -m app.mcp`) exposing Lumen tools to external agents
- `app/seeds/` — seed bundles (`demo`, `agentic_demo`, `rag_from_scratch_demo`) used by `make seed` / `make demo-seed`
- `app/cli.py` — Typer CLI for admin tasks (seed, reindex)

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
make demo-seed                     # agentic-demo bundle (3 courses + tutor turn + draft)
make test                          # backend + frontend
make test.api                      # backend only
make test.web                      # frontend unit only
make test.e2e                      # Playwright E2E against the live stack (e2e profile)
make a11y                          # WCAG 2.2 AA axe-core gate (needs `make up` first)
make eval [suite=tutor|authoring|ingest] [limit=N]   # run an eval suite
make lint / make fmt
make shell.api / make shell.web / make shell.db
make downgrade                     # alembic downgrade one revision
make reset                         # drop volumes + rebuild (DESTROYS local data)
make config.check                  # validate prod compose config
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
- **Tutor adversarial probes are OFF by default** on the standard rail — only the eval harness turns them on (ADR-0024); don't enable them on the live tutor path
- **Publish enqueues the embedding reindex _after commit_** behind an atomic phase fence (ADR-0019) — enqueuing inside the transaction races the worker against uncommitted rows
- **Search index** lives in a `GENERATED ALWAYS AS` Postgres `tsvector` column on `courses` — Postgres maintains it on every insert/update, no Celery trigger involved. The Celery reindex task is a separate path that rebuilds **lesson-chunk embeddings** for the RAG tutor (fires on publish + admin reindex only; `delete_course` is a soft-delete that doesn't enqueue). There's no separate search service — the original Meilisearch wire was retired during the rebuild (see superseded ADR-0003 / new ADR-0015).

## Where to put new things

- **New endpoint** → handler in `app/api/v1/<resource>.py`, service in `app/services/`, repo in `app/repositories/`, schema in `app/schemas/`, register in `app/api/router.py`
- **New table** → model in `app/models/<name>.py`, add to `app/models/__init__.py`, then `make revision m="add ..."` and review the generated migration
- **New UI route** → `apps/frontend/src/app/<route>/page.tsx`, components in `src/components/<area>/`, data hooks via TanStack Query with keys in `src/lib/query/keys.ts`
- **New eval case** → extend the golden/adversarial dataset under `app/evals/`; run `make eval suite=...`
- **New MCP tool** → register in `app/mcp/tools.py` (+ `server.py`); keep `app/mcp/registry_metadata.json` in sync
- **New AI subagent** → add under `app/services/tutor_subagents/` or `authoring_subagents/` and wire it into the matching orchestrator
- **New ADR** → copy `docs/adr/0000-template.md`, bump the number, add to PR description

## What to leave alone

- `.claude/ralph-loop.local.md` (loop state — read-only signal)
- Anything under `infra/` without a corresponding ADR change
