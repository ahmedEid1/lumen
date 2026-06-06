# Lumen

Lumen started in late 2020 as a Django side-project — a learning platform for myself. Five years and one model revolution later, the original prototype is gone and the question that replaced it is sharper: can a platform let *anyone* learn anything by just describing it? Tell the AI what you want to learn, get a private course built for you in about a minute, learn it with a citation-grounded tutor, then share, clone, and remix it through a moderated public catalog. Custom orchestrator, no LangChain. Groq Llama 3.3 70B for the latency-per-dollar that makes "watch it build" real. Public evals so you can audit the agent's competence yourself.

— *Ahmed Hobeishy*

*An open-source, learner-owned, AI-first LMS built as a portfolio anchor for agentic-AI engineering work.*

[![Live demo: lumen.ahmedhobeishy.tech](https://img.shields.io/badge/live%20demo-lumen.ahmedhobeishy.tech-2ea44f?style=for-the-badge&logo=amazonaws&logoColor=white)](https://lumen.ahmedhobeishy.tech)

Public deploy on AWS t4g.small (Graviton2 ARM, 2 vCPU + 2 GB RAM) — Caddy 2 fronts a single `docker-compose.prod.yml` running FastAPI + Celery + Postgres 17 (pgvector) + Redis 7 + MinIO. Real LLM calls via Groq Llama 3.3 70B; retrieval embeddings via Cloudflare Workers AI (`@cf/baai/bge-small-en-v1.5`). Runbook: [`docs/deployment/aws-vps.md`](docs/deployment/aws-vps.md).

[![CI](https://github.com/ahmedEid1/lumen/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmedEid1/lumen/actions/workflows/ci.yml)
[![authoring eval: 3.85/5 (n=10)](https://img.shields.io/badge/authoring%20eval-3.85%2F5%20(n%3D10)-success)](docs/eval/authoring-n10-groq-20260525.jsonl)
[![MCP registry](https://img.shields.io/badge/MCP%20registry-io.github.ahmedEid1%2Flumen-blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[![Watch the captioned walkthrough →](docs/screencast/walkthrough-poster.jpg)](docs/screencast/walkthrough.mp4)

![Lumen home — Workbench UI, lime accent on a dark canvas](docs/screenshots/hero.png)

---

## What this is

Lumen is a **two-role, learner-owned platform**: there is no instructor caste. Every signed-in `user` can both author and learn; `admin` manages users, moderates the public catalog, and owns platform config. The product is one loop — **define → build → learn → share → clone** — and underneath it is the actual point of the repo: a custom multi-agent system with course-scoped RAG, public evals, observable per-call traces, and an MCP server. It is the centrepiece of an agentic-AI engineering portfolio — a self-hostable LMS that doubles as a working argument for "I build production-grade AI systems, not toy demos."

Shipped to production today as **2.0.0-two-role** (see [CHANGELOG](CHANGELOG.md)) — built as a gated waterfall (requirements → design → 6 ADRs → seven build streams), each stream cleared a Codex challenge, an independent Claude review, and a live in-browser walk before merging.

## The 60-second story

1. **Define** — type a fuzzy goal ("I want to learn Postgres query optimization"). A guided AI intake asks a *bounded* set of clarifying questions (level, time budget, prior knowledge, target outcomes — capped at six turns) and distils your answers into a structured **learning brief**. The brief's source goal is field-encrypted at rest and excluded from admin views.
2. **Build** — finalize the brief and the authoring orchestrator builds a course *for you*. On the production walk with real Groq Llama 3.3 70B this produced **4 modules / 16 lessons in ~50 seconds**, with the module structure mapping verbatim to the brief's outcomes. The build reports honest status: a failure says so, keeps no half-finished partial, is re-runnable (the retry reuses the same in-flight course, never spawns duplicates), and is cancellable mid-flight.
3. **Learn** — your AI-built course is **private by default**. Learn it directly with the course-scoped RAG tutor; on the prod walk a tutor turn streamed a correct partial-index answer with a retrieval trace in ~1 second.
4. **Share** — publishing keeps a course *published-but-private*. To reach the public catalog you explicitly **share** it, which enters a `pending_review` queue. Catalog listing, lesson previews, tutor retrieval, enrollment, search, and sitemap all route through a single central authorizer (`is_publicly_listed`) — no scattered "is it published?" checks decide visibility.
5. **Admin moderation** — an admin approves (it becomes publicly listed), rejects, delists, or archives/restores a course through a proper state machine (`private → pending_review → public | rejected | delisted`) with an immutable moderation audit trail. Signed-in users can report a listed course from a reason-taxonomy dialog; crossing the report threshold flags a course for human review *without* auto-unlisting it.
6. **Clone with provenance** — any user can clone a publicly-listed course into a fresh private draft they own and remix it independently. The clone carries a server-written, read-only "Based on … by …" attribution (can't be spoofed; degrades to "no longer available" if the source is delisted or its author deleted). It is a **sanitized export projection** — only live lesson/quiz content is copied, never enrollments, progress, reviews, discussions, agent traces, signed file URLs, soft-deleted lessons, or embeddings.
7. **BYOK** — bring your own AI provider key under `/profile/model` instead of the free platform model. An **allowlisted provider registry** (OpenAI, Anthropic, Groq, Mistral) with **server-owned fixed base URLs** closes the SSRF surface by construction; keys are **envelope-encrypted** (AES-256-GCM, versioned KEK) and write-only.

---

## The agentic patterns I built

The resume bullets, with links to the code. Every item is on production today (2.0.0-two-role).

- **Custom multi-agent orchestrator — no LangChain.** The tutor reads the learner's question and picks among five sub-agents under [`app/services/tutor_subagents/`](apps/backend/app/services/tutor_subagents/) — `retriever`, `web_searcher`, `code_runner`, `quiz_generator`, `concept_explainer` — with a hard cap on tool-call rounds per turn. Streaming variant in [`tutor_orchestrator_stream.py`](apps/backend/app/services/tutor_orchestrator_stream.py). The authoring side runs researcher → outliner → critic → reviser → lesson-drafter → final-critic ([`authoring_orchestrator.py`](apps/backend/app/services/authoring_orchestrator.py) + [`authoring_subagents/`](apps/backend/app/services/authoring_subagents/)), capped at six revise/critic LLM calls. Every step lands in [`agent_tracer.py`](apps/backend/app/services/agent_tracer.py) — the moat is showing *how* the agent thinks, not just what it said.
- **Course-scoped pgvector RAG with `[L:id]` citations.** Retrieval is scoped per course and routed through a single ACL clause (`retrieval_acl_clause`, [`app/services/visibility.py`](apps/backend/app/services/visibility.py)) so a cloned/private course never leaks chunks across the authorizer (ADR-0029). Embeddings via Cloudflare Workers AI (`@cf/baai/bge-small-en-v1.5`, 384-dim, free tier); the tutor's answer points each claim at a specific lesson chunk.
- **Eval harness with LLM-as-judge + public `/eval`.** Three golden suites — 30-item tutor + 10 authoring + 10 ingest under [`apps/backend/evals/`](apps/backend/evals/) — judged 0–5 per axis, published whole (not a highlight reel). Run with `make eval` or `python -m app.evals run --suite tutor`. CI gates a 3-item smoke on every PR ([`.github/workflows/pnpm-eval-smoke.yml`](.github/workflows/pnpm-eval-smoke.yml)). Results are public read-only at [`/eval`](apps/frontend/src/app/eval/) + [`/eval/methodology`](apps/frontend/src/app/eval/methodology/).
- **Observable traces — token/cost/latency per call.** Every LLM call's prompt/completion tokens, USD cost, latency, and outcome land in the `llm_calls` table via [`llm_call_log.py`](apps/backend/app/services/llm_call_log.py). Streamed tutor turns record real token usage end-to-end (S7 closed three downstream drop seams), so streaming is no longer invisible to cost rollups. A per-user budget guard and request-COUNT quotas back it; `/admin/observability` adds queue depth + per-trace drill-down.
- **MCP server on the official registry.** [`app/mcp/server.py`](apps/backend/app/mcp/server.py) exposes nine tools over stdio + HTTP (OAuth client-credentials), published to `registry.modelcontextprotocol.io` as `io.github.ahmedEid1/lumen`. Write tools gate on the `can_author` *capability* (any active user), not a role; URL ingest stays admin-only + flag-gated by design (ADR-0025).
- **BYOK envelope encryption + prod boot guards.** Per-credential 256-bit DEK wrapped by a versioned server KEK ([`app/core/secrets_crypto.py`](apps/backend/app/core/secrets_crypto.py)); decryption happens *only* inside the dispatch path — never in `repr`, logs, traces, `llm_calls` rows, exports, admin views, or OpenAPI. A production boot guard ([`app/core/prod_guards.py`](apps/backend/app/core/prod_guards.py)) refuses to start with stored credentials but no real KEK (ADR-0027). Non-dollar request quotas close the `$0`-BYOK bypass of the dollar guard.
- **Phased migration chain with evidence gates.** The two-role rebuild migrated `student`/`instructor` → `user` with zero downtime (widen accepted role set + JWT claim → backfill → drop old values only after access tokens drain at the 15-min TTL). The Alembic chain enforces a one-phase-per-run boundary and an evidence gate that *refuses* to apply a backfill across a fence with un-backfilled rows (caught a real prod data condition at deploy time — 85 legacy chunks with NULL embedding model).

---

## How it's built and tested

The process is the portfolio as much as the code. Each build stream ran through three gates before merge:

- **Gate A — Codex challenge:** the Codex CLI as a second brain attacks the artifact (design, plan, code). Findings triaged and resolved.
- **Gate B — independent Claude reviewer:** a gating review subagent re-checks against source until clean.
- **Gate C — live evidence:** drive the app as a real user in a browser (local, then prod after deploy) on top of unit/e2e/a11y. Running-the-app evidence is required, not optional.

Suite sizes at the 2.0.0 release: **backend 1421 tests, frontend 468 tests**, all green. WCAG 2.2 AA axe-core gate (13 a11y checks, 0 violations), en + ar i18n parity, visual-regression baselines, and Playwright E2E on **both** Chromium and WebKit. CI gates production and a green `main` auto-deploys.

---

## Run it locally

**Prereqs.** Docker Desktop 4.30+ (or Docker Engine 27 + Compose v2). Optional: an LLM API key — a Groq key is recommended for the free tier; without one, the AI features fall back to the deterministic `noop` provider so the rest of the app still works.

```bash
git clone https://github.com/ahmedEid1/lumen.git
cd lumen
cp .env.example .env
make up           # bring the full dev stack up
make migrate      # alembic upgrade head
make seed         # demo data (admin + two users)
```

Then open <http://localhost:3000> and log in with one of the seeded accounts:

| Role  | Email              | Password    |
|-------|--------------------|-------------|
| admin | admin@lumen.test   | Admin!2026  |
| user  | teacher@lumen.test | Teach!2026  |
| user  | student@lumen.test | Learn!2026  |

Both `teacher@` and `student@` are plain `user` accounts now — they can author *and* learn; the only role distinction is `admin`. (`make demo-seed` loads the richer agentic-demo bundle: 3 courses + a tutor turn + a draft.)

For real LLM features (define/build, tutor, evals), set the following in `.env` and restart:

```env
LLM_PROVIDER=openai
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_API_KEY=<your-groq-key>
LLM_MODEL=llama-3.3-70b-versatile
```

The same `LLMProvider` abstraction also accepts native Anthropic (`LLM_PROVIDER=anthropic`) and OpenAI configurations — no code changes, switch by env var. The optional feature flags (`FEATURE_BYOK_ENABLED`, `FEATURE_PRIVATE_PUBLISH_ENABLED`, `CLONE_ENABLED`) ship **off**; flip them in `.env` once their prerequisites (e.g. a real BYOK master key) are in place.

---

## Stack

- **Backend:** Python 3.13, FastAPI, async SQLAlchemy 2, Alembic, Celery, structlog
- **Frontend:** Next.js 15 (App Router, RSC), React 19, TypeScript 5, Tailwind 4, shadcn-style primitives, TanStack Query
- **Data:** PostgreSQL 17 (`pgvector` + `tsvector` full-text search), Redis 7, MinIO (S3-compatible)
- **AI:** custom orchestrator (no LangChain); Groq Llama 3.3 70B over an OpenAI-compatible client; Cloudflare Workers AI embeddings; allowlisted BYOK providers (OpenAI / Anthropic / Groq / Mistral)
- **Delivery:** Docker Compose (dev + prod), GitHub Actions CI/CD, Trivy + CodeQL + gitleaks, Caddy 2

---

## Architecture

```mermaid
flowchart LR
    user([User · authors + learns])
    admin([Admin · moderates + config])

    subgraph Edge[Edge]
      web[Next.js 15<br/>App Router · RSC<br/>Docker on EC2]
    end

    subgraph App[Application]
      api[FastAPI · Python 3.13<br/>capability-based authz<br/>Docker on EC2]
      worker[Celery worker + beat<br/>Docker on EC2]
    end

    subgraph Agents[Agent layer]
      define[Goal intake<br/>→ learning brief]
      authoring[Authoring orchestrator<br/>researcher → … → final-critic]
      tutor[Tutor orchestrator<br/>+ 5 sub-agents]
      pathagent[Learning-path agent]
    end

    subgraph MCP[MCP surface]
      mcp[Lumen MCP server<br/>9 tools · capability-gated<br/>io.github.ahmedEid1/lumen]
    end

    subgraph Data[Data plane]
      pg[(Postgres 17 + pgvector<br/>central is_publicly_listed authorizer<br/>Docker on EC2)]
      redis[(Redis 7<br/>Docker on EC2)]
      s3[(MinIO S3-compatible<br/>Docker on EC2)]
    end

    subgraph LLM[Swappable LLM layer]
      provider{LLM_PROVIDER<br/>platform key · or per-user BYOK}
      groq[Groq · Llama 3.3 70B<br/>free · platform default]
      byok[BYOK allowlist<br/>OpenAI · Anthropic · Mistral<br/>envelope-encrypted keys]
    end

    subgraph Eval[Eval loop]
      golden[(Golden datasets<br/>tutor · authoring · ingest)]
      judge[LLM-as-judge<br/>0–5 per axis]
      meter[llm_calls table<br/>tokens · cost · latency]
    end

    user --> web
    admin --> web
    web --> api
    api --> pg
    api --> redis
    api --> s3
    api --> worker
    worker --> pg
    api --> define
    define --> authoring
    api --> tutor
    api --> pathagent
    tutor --> pg
    mcp --> api
    authoring --> provider
    tutor --> provider
    pathagent --> provider
    provider -.platform.-> groq
    provider -.per-user.-> byok
    api --> meter
    golden --> judge
    judge --> provider
```

Provider-agnostic LLM layer: the live demo runs Groq Llama 3.3 70B on the free tier; users can dispatch on their own allowlisted key. Every agent call goes through the cost meter so observability and the budget/quota guards work identically across providers. Full topology: [docs/architecture.md](docs/architecture.md).

---

## Use Lumen from Claude Desktop

Lumen ships an MCP server that exposes its catalog, RAG tutor, FSRS review queue, AI authoring, and ingest as nine tools. Add it as an MCP source in Claude Desktop:

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json (macOS)
// %APPDATA%\Claude\claude_desktop_config.json (Windows)
{
  "mcpServers": {
    "lumen": {
      "command": "python",
      "args": ["-m", "app.mcp", "--transport", "stdio"],
      "env": {
        "LUMEN_MCP_AUTH_TOKEN": "<your-client-secret>",
        "DATABASE_URL": "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen"
      }
    }
  }
}
```

Mint the `LUMEN_MCP_AUTH_TOKEN` with `make mcp-token` against your running instance — it prints a fresh OAuth `client_id` + `client_secret`; paste the secret. For Claude Code: `LUMEN_MCP_AUTH_TOKEN=<client_secret> claude mcp add lumen -- python -m app.mcp --transport stdio`. Once installed, ask Claude `'list my Lumen courses'` and watch the tool calls fire — the model picks among `list_courses`, `get_course`, `search_lesson_content`, `ask_tutor`, `list_my_due_reviews`, `grade_review_card`, `create_course_draft`, `ingest_url_to_draft`, and `list_my_progress`. The write tools (`create_course_draft`, `ingest_url_to_draft`) gate on the `can_author` capability; URL ingest is admin-only and flag-gated. Full operator guide: [docs/mcp.md](docs/mcp.md).

---

## Status, limits, and honesty

- **Live** at [lumen.ahmedhobeishy.tech](https://lumen.ahmedhobeishy.tech) — 2.0.0-two-role shipped 2026-06-06. `main` is canonical; a green `main` auto-deploys.
- **Email verification is disabled on production.** `EMAIL_ENABLED=false` until a real SMTP provider is configured (the prod host never had SMTP). Signup works without a verification round-trip; this is a flag, not a code limitation.
- **The live demo runs on the free tier** — Groq Llama 3.3 70B + Cloudflare Workers AI embeddings + a single AWS t4g.small. A per-user budget guard and non-dollar request quotas cap spend; expect free-tier latency under load.
- **Published eval numbers include the weak ones** — authoring 3.85/5 (n=10) is strong; tutor and ingest scores are early with documented causes. See [`/eval`](https://lumen.ahmedhobeishy.tech/eval) and the [`docs/eval/`](docs/eval/) JSONL reports — every score is measured, reproducible, and gated by a CI smoke on every PR.

**Links:** [Live demo](https://lumen.ahmedhobeishy.tech) · [/eval](https://lumen.ahmedhobeishy.tech/eval) · [CHANGELOG](CHANGELOG.md) · [ADRs](docs/adr/) (0025–0030 cover the two-role rebuild) · [Architecture](docs/architecture.md) · [MIT License](LICENSE)

---

## Built by

**Ahmed Hobeishy** — AI / Agent Engineer based in Essen, Germany. I build LLM agents you can trust — measured with golden evals, per-claim citation checks, and full tracing — on a foundation of 3+ years shipping production software. Lumen is the centrepiece of that work.

**Open to AI / Agent Engineer roles in Germany where evaluation and observability are first-class.**

- LinkedIn: <https://www.linkedin.com/in/ahmedhobeishy/>
- GitHub: <https://github.com/ahmedEid1>
- Reach out via LinkedIn, or open an issue on this repo.
