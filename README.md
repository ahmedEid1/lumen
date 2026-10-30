<div align="center">

# Lumen

**Type a one-sentence learning goal. An AI orchestrator builds you a private course (about 45 s for 10 lessons),
a course-scoped RAG tutor teaches it with lesson citations, and you can audit every agent decision it made.**

<sub>Custom multi-agent system, no LangChain · public evals with the weak scores kept in · ran in production on AWS, May to October 2026</sub>

[![CI](https://img.shields.io/github/actions/workflow/status/ahmedEid1/lumen/ci.yml?style=flat-square&label=CI)](https://github.com/ahmedEid1/lumen/actions/workflows/ci.yml)
[![authoring eval 3.85/5 (n=10)](https://img.shields.io/badge/authoring%20eval-3.85%2F5%20(n%3D10)-2ea44f?style=flat-square)](docs/eval/)
[![MCP registry](https://img.shields.io/badge/MCP%20registry-io.github.ahmedEid1%2Flumen-blue?style=flat-square)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](LICENSE)

[**Walkthrough video**](docs/demo/2026-10-30/video/lumen-walkthrough.mp4) · [**Screenshots**](docs/demo/2026-10-30/) · [**Eval results**](docs/eval/) · [**Architecture**](docs/architecture.md) · [**MCP server**](docs/mcp.md)

<img src="docs/screenshots/gifs/define-build.gif" alt="Real production recording. A one-sentence goal becomes a learning brief, then the authoring orchestrator builds a 4-module, 16-lesson private course." width="900">

<sub>Production recording from May 2026, on Groq Llama 3.3 70B (since retired). Intake sped up 6×, build 16×; the brief and the finished course play in real time.<br>
Today a 10-lesson course builds in about 45 s after the intake, on Groq gpt-oss-120b (median of 3 production builds, October 2026).<br>
The hosted demo was retired on 2026-10-30. [The walkthrough video and screenshots](docs/demo/2026-10-30/) record its last live version; run it locally with the quick start below, or [redeploy it](docs/deployment/REDEPLOY.md).</sub>

</div>

## What this is

A **learner-owned, two-role e-learning platform** — every signed-in user runs the whole loop themselves; `admin` only moderates and configures. The product is the loop; the point of the repo is the agentic system underneath it.

| Step | What happens |
|---|---|
| **Define** | A guided AI intake (capped at six turns) turns a fuzzy goal into a structured **learning brief** — the source goal is field-encrypted at rest |
| **Build** | The authoring orchestrator builds a **private course** from the brief — honest status, no half-finished partials, re-runnable, cancellable ([`build.py`](apps/backend/app/services/build.py), the durability/idempotency/quota shell) |
| **Learn** | A **course-scoped RAG tutor** answers with lesson citations and a visible tool-call trace |
| **Share** | Publishing stays private; public listing is an explicit share + admin moderation state machine with an immutable audit trail |
| **Clone** | Any listed course can be remixed into your own draft, with server-written "Based on …" provenance and a sanitized export (no enrollments, traces, or soft-deleted content) |
| **BYOK** | Bring your own model key (OpenAI / Anthropic / Groq / Mistral) — allowlisted providers, server-owned base URLs, envelope-encrypted write-only keys |

Shipped to production as **2.0.0-two-role** ([CHANGELOG](CHANGELOG.md)) — built as a gated waterfall: requirements → design → 6 ADRs → seven build streams, each cleared a Codex challenge, an independent Claude review, and a live in-browser walk before merge.

## The agentic layer

Everything below ran in the hosted demo, with the code one click away. One exception: the web tutor streams a simpler retrieve-then-answer path (next section).

### Custom multi-agent orchestrator — no frameworks

The tutor's planner picks per turn among five sub-agents in [`tutor_subagents/`](apps/backend/app/services/tutor_subagents/) — `retriever`, `web_searcher`, `code_runner`, `quiz_generator`, `concept_explainer` — with a cap of five tool-call rounds ([`tutor_orchestrator.py`](apps/backend/app/services/tutor_orchestrator.py)). The planner runs behind the tutor API (`POST /api/v1/tutor/conversations/{id}/messages`) and the MCP `ask_tutor` tool. `web_searcher` is off in production, because no Tavily key is set there.

The web tutor streams a shorter path ([`tutor_orchestrator_stream.py`](apps/backend/app/services/tutor_orchestrator_stream.py)): one course-scoped retrieval (top 6 chunks) and one streamed answer. It shows a plan step, but no planner call runs.

The authoring side runs a six-stage pipeline — researcher → outliner → critic → reviser → lesson-drafter → final-critic — in [`authoring_orchestrator.py`](apps/backend/app/services/authoring_orchestrator.py), capped at six revise/critic calls.

<div align="center">
<img src="docs/screenshots/gifs/tutor.gif" alt="The RAG tutor streaming an answer: question sent, retriever sub-agent fires with its latency visible, answer streams in (2× speed)" width="900">

<sub>Production recording at 2× — the retriever fires (latency on-screen), then the answer streams.</sub>
</div>

### Course-scoped RAG with citations, behind one authorizer

Retrieval is scoped per course and routed through a single ACL clause ([`visibility.py`](apps/backend/app/services/visibility.py), ADR-0029) so private and cloned courses never leak chunks. Embeddings come from Cloudflare Workers AI (`@cf/baai/bge-small-en-v1.5`, 384 dims) and are stored in `pgvector` with an HNSW cosine index. Lessons are split into chunks of about 500 tokens with a 50-token overlap. Retrieval is cosine top-k, with the access check in the same SQL query. Answers cite the lessons they draw on (`[L:<lesson_id>]`), and links are built only for lessons that were retrieved.

### Every agent decision is auditable

Each LLM call logs prompt/completion tokens, USD cost, latency, and outcome to the `llm_calls` table ([`llm_call_log.py`](apps/backend/app/services/llm_call_log.py)); each agent step lands in [`agent_tracer.py`](apps/backend/app/services/agent_tracer.py). Learners get a per-turn **"show me how you got this"** drill-down — planner steps, tool calls, retrieval audits with similarity scores; authors get a step-by-step **build replay**.

<div align="center">

| Tutor-turn trace | Authoring build replay |
|---|---|
| <img src="docs/screenshots/agent-trace.png" alt="Trace drill-down: step-by-step timeline with planner, tool calls, retriever and synthesiser steps, plus retrieval audit cards showing per-chunk similarity scores" width="440"> | <img src="docs/screenshots/studio-replay.png" alt="AI authoring replay: 8 orchestrator steps with per-step durations and the researcher step's prompt and response expanded" width="440"> |

</div>

### Eval harness with LLM-as-judge — published whole

Three golden suites (30-item tutor, 10 authoring, 10 ingest) under [`evals/`](apps/backend/evals/), judged 0–5 per axis, plus adversarial probes. Every PR runs a CI smoke that exercises the harness on a noop provider ([workflow](.github/workflows/pnpm-eval-smoke.yml)); the score gate needs a model key and doesn't run yet. Results are public at [/eval](https://lumen.ahmedhobeishy.tech/eval).

The harness matters more than the scores: LLM-as-judge on one strong subsystem and two early ones, and every number can be re-run with `make eval suite=…`. All three runs below are from 2026-05-25, with Groq Llama 3.3 70B (now retired) as both model and judge.

| Suite | Judged | LLM-judge score | Reading |
|---|---:|---:|---|
| Authoring | 10 / 10 | **3.85 / 5** | Strong — the headline number, backed by [the raw JSONL](docs/eval/authoring-n10-groq-20260525.jsonl) |
| Tutor | 10 / 30 | 2.33 / 5 | Early — citation_correctness 0.9/5 comes from a label bug: the synthesiser headed excerpts `Lesson L<id>`, the model cited `[L:L<id>]`, and validation dropped those citations. 6 of the 7 answers that didn't refuse cited the right lesson in that form. The fix is in [PR #21](https://github.com/ahmedEid1/lumen/pull/21); the suite has not been re-run since. 20 items were skipped because their two courses were not seeded |
| Ingest | 4 / 10 | 0.83 / 5 | Early — the 4 judged items scored low on chapter count and structure, because the v1 chunker makes one module per video. 6 items errored: one 465-lesson video broke the 200-lesson module cap, one Notion item had no `NOTION_TOKEN` in the eval env, and four dataset URLs are Notion help-center pages with no page ID |

The weak scores are published whole, on purpose. [Methodology and raw reports](docs/eval/).

### MCP server on the official registry

[`app/mcp/`](apps/backend/app/mcp/) exposes nine tools (catalog, RAG tutor, FSRS reviews, AI authoring, ingest) over stdio + HTTP with OAuth client-credentials, published as [`io.github.ahmedEid1/lumen`](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen). Write tools gate on the `can_author` capability; URL ingest stays admin-only + flag-gated (ADR-0025).

Wiring it into an MCP client takes one JSON block:

<details>
<summary><b>Use it from Claude Desktop / Claude Code</b></summary>

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "lumen": {
      "command": "python",
      "args": ["-m", "app.mcp", "--transport", "stdio"],
      "env": {
        "LUMEN_MCP_AUTH_TOKEN": "<client-secret from `make mcp-token`>",
        "DATABASE_URL": "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen"
      }
    }
  }
}
```

Or for Claude Code: `LUMEN_MCP_AUTH_TOKEN=<secret> claude mcp add lumen -- python -m app.mcp --transport stdio`, then ask *"list my Lumen courses"* and watch `list_courses`, `ask_tutor`, `create_course_draft`, … fire. Full operator guide: [docs/mcp.md](docs/mcp.md).

</details>

### BYOK without the foot-guns

Per-credential 256-bit DEKs wrapped by a versioned server KEK ([`secrets_crypto.py`](apps/backend/app/core/secrets_crypto.py)); decryption only inside the dispatch path — never in logs, traces, exports, or admin views. A [prod boot guard](apps/backend/app/core/prod_guards.py) refuses to start with stored credentials but no real KEK (ADR-0027). Request-count quotas close the `$0`-BYOK bypass of the dollar budget guard.

### Zero-downtime phased migrations with evidence gates

The two-role rebuild migrated `student`/`instructor` → `user` live: widen accepted roles → backfill → drop old values only after access tokens drained their 15-min TTL. The Alembic chain enforces one phase per run, and migration-level evidence gates refuse to tighten constraints over un-backfilled rows — one of them caught a real prod data condition (85 legacy chunks with NULL embedding model) at deploy time.

## Architecture

The short version: one FastAPI service owns all invariants, the agents are plain service-layer code, and every LLM call crosses one provider seam and one cost meter.

```mermaid
flowchart LR
    user([User · authors + learns])
    admin([Admin · moderates + config])

    subgraph App[Application]
      web[Next.js 15 · RSC]
      api[FastAPI · Python 3.13<br/>capability-based authz<br/>central is_publicly_listed authorizer]
      worker[Celery worker + beat]
    end

    subgraph Agents[Agent layer]
      define[Goal intake → brief]
      authoring[Authoring orchestrator<br/>researcher → … → final-critic]
      tutor[Tutor orchestrator<br/>+ 5 sub-agents]
    end

    subgraph Data[Data]
      pg[(Postgres 17 + pgvector)]
      redis[(Redis 7)]
      s3[(MinIO S3)]
    end

    subgraph LLM[Swappable LLM layer]
      provider{LLM_PROVIDER dispatch}
      groq[Groq · gpt-oss-120b]
      byok[BYOK allowlist<br/>OpenAI · Anthropic · Mistral · Groq]
    end

    subgraph Eval[Eval loop]
      golden[(Golden datasets)]
      judge[LLM-as-judge 0–5]
      meter[llm_calls<br/>tokens · cost · latency]
    end

    user --> web --> api --> pg
    admin --> web
    api --> redis & s3 & worker
    api --> define --> authoring
    api --> tutor --> pg
    mcp[MCP server · 9 tools] --> api
    authoring & tutor --> provider
    provider -.platform.-> groq
    provider -.per-user.-> byok
    api --> meter
    golden --> judge --> provider
```

Provider-agnostic by env var — the hosted demo ran on Groq's free tier; users dispatch on their own allowlisted keys. Every call crosses the cost meter, so budgets, quotas, and observability behave identically across providers. Full topology: [docs/architecture.md](docs/architecture.md).

**Stack:** Python 3.13 · FastAPI · async SQLAlchemy 2 · Alembic · Celery — Next.js 15 · React 19 · TypeScript 5 · Tailwind 4 · TanStack Query — PostgreSQL 17 (`pgvector` + `tsvector`) · Redis 7 · MinIO — Docker Compose · GitHub Actions · Trivy + CodeQL + gitleaks · Caddy 2.

## How it's built and tested

The process is the portfolio as much as the code. Every build stream cleared three gates before merge:

1. **Codex challenge** — a second-brain CLI attacks the design, plan, and code; findings triaged and resolved.
2. **Independent Claude review** — a gating review subagent re-checks against source until clean.
3. **Live evidence** — drive the app as a real user in a browser, locally and on prod, on top of unit/E2E/a11y suites. Running-the-app evidence is required, not optional.

At the 2.0.0 release: **backend 1,421 tests / frontend 468 tests**, all green; WCAG 2.2 AA axe-core gate (11 surfaces, 0 violations); en + ar i18n parity; visual-regression baselines; Playwright E2E on Chromium **and** WebKit. The UI itself went through a 20-loop redesign (30+ Radix-backed primitives, ⌘K command palette, dark/light themes) with five in-loop Codex rescue passes plus a final Codex review. A green `main` auto-deploys to production.

<div align="center">
<img src="docs/screenshots/gifs/cmdk.gif" alt="Command palette: Ctrl+K opens it over the dashboard, typing filters live course search results alongside navigation, theme, and account commands" width="700">

<sub><kbd>⌘K</kbd> — navigate, search courses, switch theme, sign out.</sub>
</div>

## Run it locally

Prereqs: Docker Desktop 4.30+ (or Engine 27 + Compose v2).

```bash
git clone https://github.com/ahmedEid1/lumen.git
cd lumen
cp .env.example .env
make up && make migrate && make seed
```

Open <http://localhost:3000> and sign in with one of the local seed logins. They exist only in the database `make seed` creates on your machine. The hosted app never used them; its public demo account is gone with the hosted demo.

| Role | Email | Password (local only) |
|---|---|---|
| admin | `admin@lumen.test` | `Admin!2026` |
| user | `teacher@lumen.test` | `Teach!2026` |
| user | `student@lumen.test` | `Learn!2026` |

Without an LLM key the AI features fall back to a deterministic `noop` provider — the rest of the app still works. For the real thing (define/build, tutor, evals), a free Groq key is enough:

```env
LLM_PROVIDER=openai
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_API_KEY=<your-groq-key>
LLM_MODEL=openai/gpt-oss-120b
```

The same `LLMProvider` abstraction takes native Anthropic or OpenAI by env var — no code changes. Feature flags (`FEATURE_BYOK_ENABLED`, `FEATURE_PRIVATE_PUBLISH_ENABLED`, `CLONE_ENABLED`, `FEATURE_TUTOR_STREAMING`) default **off**; set them in `.env` once their prerequisites (e.g. a real BYOK master key) are in place. `make demo-seed` adds the richer agentic-demo bundle.

<details>
<summary><b>More screenshots</b> — dashboard, catalog, the agent-replay home page, the public eval page, a freshly built course, the brief review</summary>

| | |
|---|---|
| ![Learner dashboard with in-progress courses and the "create a course to learn" entry](docs/screenshots/dashboard.png) | ![Public catalog with subject filters and tag rail](docs/screenshots/catalog.png) |
| ![The home page: an agent-replay hero that walks through a real tutor turn](docs/screenshots/home.png) | ![Public eval page: honest scores with a sealed-run badge](docs/screenshots/eval-page.png) |
| ![A freshly built private course in the three-column learn workbench](docs/screenshots/built-course.png) | ![Brief review: level, time budget, outcomes — nothing builds until you confirm](docs/screenshots/brief-review.png) |

</details>

## Status, limits, and honesty

- **Hosted demo retired on 2026-10-30.** It ran at lumen.ahmedhobeishy.tech from 2026-05-25 (2.0.0-two-role from 2026-06-06) on Groq + Cloudflare Workers AI + one AWS t4g.small built with [Terraform](infra/aws/) and deployed by CI after every gate passed ([runbook](docs/deployment/aws-vps.md)). The domain now redirects here. Recordings of the last live version: [docs/demo/2026-10-30/](docs/demo/2026-10-30/). To bring it back with the last production data: [docs/deployment/REDEPLOY.md](docs/deployment/REDEPLOY.md).
- **Models in the hosted demo:** Groq `openai/gpt-oss-120b`, falling back to `openai/gpt-oss-20b`; quizzes and critic scorecards run on `openai/gpt-oss-20b` (`LLM_LIGHT_MODEL`), all with reasoning effort low.
- **Email verification was off in the hosted demo** (`EMAIL_ENABLED=false`, no SMTP configured). A flag, not a code limitation.
- **Eval scores include the weak ones**, with causes documented — see the table above and [docs/eval/](docs/eval/) for raw JSONL.
- **Test counts are release-time snapshots** (the suites keep moving with `main`); CI is the live source of truth.

## Built by

**Ahmed Hobeishy**, AI Engineer for agentic systems, Germany.

Lumen started as a 2020 Django side project. Today it is where I build agentic systems and course-scoped RAG: a multi-agent course builder, a RAG tutor that cites the lessons it draws on, per-call cost and latency traces, and public evals that keep the weak scores in.

[Portfolio](https://ahmedhobeishy.tech) · [LinkedIn](https://www.linkedin.com/in/ahmedhobeishy/) · [GitHub](https://github.com/ahmedEid1) · [ahmedhobeishy@gmail.com](mailto:ahmedhobeishy@gmail.com) · or open an issue here.
