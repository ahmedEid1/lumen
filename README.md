<div align="center">

# Lumen

**Type a one-sentence learning goal — an AI orchestrator builds you a private course in ~50 seconds,
a RAG tutor with citations teaches it, and you can audit every agent decision it made.**

<sub>Custom multi-agent system, no LangChain · public evals with the weak scores kept in · live in production</sub>

[![CI](https://img.shields.io/github/actions/workflow/status/ahmedEid1/lumen/ci.yml?style=flat-square&label=CI)](https://github.com/ahmedEid1/lumen/actions/workflows/ci.yml)
[![authoring eval 3.85/5 (n=10)](https://img.shields.io/badge/authoring%20eval-3.85%2F5%20(n%3D10)-2ea44f?style=flat-square)](https://lumen.ahmedhobeishy.tech/eval)
[![MCP registry](https://img.shields.io/badge/MCP%20registry-io.github.ahmedEid1%2Flumen-blue?style=flat-square)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](LICENSE)

[**Live demo**](https://lumen.ahmedhobeishy.tech) · [**Eval results**](https://lumen.ahmedhobeishy.tech/eval) · [**Architecture**](docs/architecture.md) · [**MCP server**](docs/mcp.md)

<img src="docs/screenshots/gifs/define-build.gif" alt="Real production recording. A one-sentence goal becomes a learning brief, then the authoring orchestrator builds a 4-module, 16-lesson private course." width="900">

<sub>Real production recording (Groq Llama 3.3 70B). Intake trimmed 6×, the ~50 s build 16× — the brief and the finished course are real-time.<br>
Try it yourself: [the one-click demo](https://lumen.ahmedhobeishy.tech/demo) pre-fills `demo@lumen.test` / `Demo!2026` and drops you into the tutor (free-tier box — give a cold page a few seconds).</sub>

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

Every item below is on production today, with the code one click away.

### Custom multi-agent orchestrator — no frameworks

The tutor picks per-turn among five sub-agents in [`tutor_subagents/`](apps/backend/app/services/tutor_subagents/) — `retriever`, `web_searcher`, `code_runner`, `quiz_generator`, `concept_explainer` — under a hard cap on tool-call rounds ([streaming variant](apps/backend/app/services/tutor_orchestrator_stream.py)). The authoring side runs a six-stage pipeline — researcher → outliner → critic → reviser → lesson-drafter → final-critic — in [`authoring_orchestrator.py`](apps/backend/app/services/authoring_orchestrator.py), capped at six revise/critic calls.

<div align="center">
<img src="docs/screenshots/gifs/tutor.gif" alt="The RAG tutor streaming an answer: question sent, retriever sub-agent fires with its latency visible, answer streams in (2× speed)" width="900">

<sub>Production recording at 2× — the retriever fires (latency on-screen), then the answer streams.</sub>
</div>

### Course-scoped RAG with citations, behind one authorizer

Retrieval is scoped per course and routed through a single ACL clause ([`visibility.py`](apps/backend/app/services/visibility.py), ADR-0029) so private and cloned courses never leak chunks. Embeddings via Cloudflare Workers AI (`bge-small-en-v1.5`, 384-dim) into `pgvector`; answers cite specific lesson chunks.

### Every agent decision is auditable

Each LLM call logs prompt/completion tokens, USD cost, latency, and outcome to the `llm_calls` table ([`llm_call_log.py`](apps/backend/app/services/llm_call_log.py)); each agent step lands in [`agent_tracer.py`](apps/backend/app/services/agent_tracer.py). Learners get a per-turn **"show me how you got this"** drill-down — planner steps, tool calls, retrieval audits with similarity scores; authors get a step-by-step **build replay**.

<div align="center">

| Tutor-turn trace | Authoring build replay |
|---|---|
| <img src="docs/screenshots/agent-trace.png" alt="Trace drill-down: step-by-step timeline with planner, tool calls, retriever and synthesiser steps, plus retrieval audit cards showing per-chunk similarity scores" width="440"> | <img src="docs/screenshots/studio-replay.png" alt="AI authoring replay: 8 orchestrator steps with per-step durations and the researcher step's prompt and response expanded" width="440"> |

</div>

### Eval harness with LLM-as-judge — published whole

Three golden suites (30-item tutor, 10 authoring, 10 ingest) under [`evals/`](apps/backend/evals/), judged 0–5 per axis, plus adversarial probes. A 3-item smoke gates every PR ([workflow](.github/workflows/pnpm-eval-smoke.yml)); results are public at [/eval](https://lumen.ahmedhobeishy.tech/eval).

**The point isn't the scores — it's the harness**: LLM-as-judge applied honestly to one strong subsystem and two early ones, every number reproducible with `make eval suite=…` and smoke-gated in CI.

| Suite | Judged | LLM-judge score | Reading |
|---|---:|---:|---|
| Authoring | 10 / 10 | **3.85 / 5** | Strong — the headline number, backed by [the raw JSONL](docs/eval/authoring-n10-groq-20260525.jsonl) |
| Tutor | 10 / 30 | 2.33 / 5 | Early — citation-format mismatch between the judge's expected citations and what the retriever pulls; 20 items skipped, cause documented |
| Ingest | 4 / 10 | 0.83 / 5 | Early — v1 chunker emits one module per video; 6 items failed upstream transcript fetch before judging |

The weak scores are published whole, on purpose. [Methodology](https://lumen.ahmedhobeishy.tech/eval/methodology) · [raw reports](docs/eval/).

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
      groq[Groq · Llama 3.3 70B]
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

Provider-agnostic by env var — the live demo runs Groq's free tier; users dispatch on their own allowlisted keys. Every call crosses the cost meter, so budgets, quotas, and observability behave identically across providers. Full topology: [docs/architecture.md](docs/architecture.md).

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

Open <http://localhost:3000> and sign in:

| Role | Email | Password |
|---|---|---|
| admin | `admin@lumen.test` | `Admin!2026` |
| user | `teacher@lumen.test` | `Teach!2026` |
| user | `student@lumen.test` | `Learn!2026` |

Without an LLM key the AI features fall back to a deterministic `noop` provider — the rest of the app still works. For the real thing (define/build, tutor, evals), a free Groq key is enough:

```env
LLM_PROVIDER=openai
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_API_KEY=<your-groq-key>
LLM_MODEL=llama-3.3-70b-versatile
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

- **Live** at [lumen.ahmedhobeishy.tech](https://lumen.ahmedhobeishy.tech) — 2.0.0-two-role, shipped 2026-06-06. Free tier end-to-end: Groq + Cloudflare Workers AI + one AWS t4g.small (runbook: [docs/deployment/aws-vps.md](docs/deployment/aws-vps.md)). Budget guards and request quotas cap spend; expect free-tier latency under load.
- **Email verification is off in prod** (`EMAIL_ENABLED=false` — no SMTP configured). A flag, not a code limitation.
- **Eval scores include the weak ones**, with causes documented — see the table above and [docs/eval/](docs/eval/) for raw JSONL.
- **Test counts are release-time snapshots** (the suites keep moving with `main`); CI is the live source of truth.

## Built by

**Ahmed Hobeishy** — AI / Agent Engineer in Essen, Germany. Lumen started as a 2020 Django side-project; five years and one model revolution later it's the centrepiece of my agentic-AI work: agents that are **measured** (golden evals, LLM-as-judge), **auditable** (per-call cost/latency traces, citation checks), and **shipped** (live, CI-gated, self-hostable).

**Open to AI / Agent Engineer roles in Germany where evaluation and observability are first-class.**

[LinkedIn](https://www.linkedin.com/in/ahmedhobeishy/) · [GitHub](https://github.com/ahmedEid1) · or open an issue here.
