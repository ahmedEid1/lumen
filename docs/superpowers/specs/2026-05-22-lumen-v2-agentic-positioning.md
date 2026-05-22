# Lumen v2 — Production grade + Agentic-AI portfolio positioning

| Field           | Value                                                            |
|-----------------|------------------------------------------------------------------|
| Status          | Approved — to execute in the next session                        |
| Date            | 2026-05-22                                                        |
| Branch          | `Rewrite` (continue from rebuild release `f9093b6` + Phase G)    |
| Predecessor     | `docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md`      |
| Owner           | Ahmed Hobeishy ([@ahmedEid1](https://github.com/ahmedEid1), Essen, Germany, [LinkedIn](https://www.linkedin.com/in/ahmedhobeishy/)) |

## 0. Why this exists

The 1.0.0-rebuild ships a credible self-hostable AI-first LMS. The next chapter has two intertwined goals:

1. **Production-grade hardening** of what's already built — currently the AI features wire up against `LLM_PROVIDER=noop` for tests and have no observability, no evals, no live deployment, no token-cost tracking.
2. **Agentic-AI portfolio positioning** — the owner is targeting agentic-AI engineering roles (Anthropic, OpenAI, Mistral, frontier labs and the Cursor/Replit/Vercel tier). The market signals (May 2026, Stanford AI Index) are unambiguous:
   - Agentic-AI job postings: +280% YoY, ~90k US openings, $190k avg / $300–550k senior TC.
   - Hardest-to-fake portfolio signal: **evaluation rigor**.
   - Hottest standard: **MCP** — 10k active public servers, 97M monthly SDK downloads, donated to the Linux Foundation's AAIF in Dec 2025.
   - What recruiters engage with: live demos (80% more engagement than static code), end-to-end production projects, traces of how agents *think*.

Lumen has the bones to become *the* portfolio anchor. This spec turns it from "credible LMS" into "agentic-AI engineering signature project."

## 1. Constraints that survive

- The Workbench visual (Phase C) stays.
- Architecture B+ (AI-first OSS LMS) stays.
- All 38 commits on `Rewrite` stay; no rewriting history.
- i18n / RTL / WCAG 2.2 AA stay.
- Self-hostable + open-source stays.
- No payments / no live video (the original PRD non-goals).

## 2. Phase H — Production-grade hardening

Each item ships as one commit, can be dispatched as a parallel agent.

### H1 — Real LLM call path (Anthropic + OpenAI, with cost tracking)

- Default `LLM_PROVIDER` in prod = `anthropic` (Claude Sonnet 4.6).
- Add a `LLMCostMeter` middleware that records every call's prompt/completion tokens, model, cost-USD, latency, success/error per `(user_id, feature)`.
- Backend: new table `llm_calls` (call_id, user_id, feature, model, prompt_tokens, completion_tokens, cost_usd, latency_ms, status, created_at). Migration 0022.
- Surface in `/admin/observability` page (admin-only): per-feature cost-per-day chart, top-5 expensive calls of the week.
- Per-user budget guard: if a single user's cost in 24h exceeds a configurable threshold, the next LLM call returns a friendly "cool down" message + alerts admin.

### H2 — Eval harness with LLM-as-judge + golden datasets

This is the *single highest-signal* item for the portfolio. The market consensus: evaluation rigor is the hardest-to-fake skill, and most candidates have nothing.

- Golden datasets under `apps/backend/evals/`:
  - `tutor/` — 30 hand-curated (question, ideal_answer, lesson_id, must_cite_lessons) tuples across 3 seed courses.
  - `authoring/` — 10 (brief, ideal_outline) tuples where ideal_outline has 3-6 modules with 3-5 lessons each.
  - `ingest/` — 5 YouTube URLs + 5 Notion URLs with expected chapter counts and at least one expected key phrase per chapter.
- Runner: `python -m app.evals run --suite tutor` runs the suite, calls the live tutor against each item, judges with Claude Sonnet 4.6 ("rate 0–5: faithfulness, citation correctness, helpfulness"), writes a JSONL report.
- A `/admin/evals` dashboard surface (admin-only): for each suite, latest run's mean score, per-item drill-down, regression vs. previous run.
- CI step: `pnpm-eval-smoke` runs a 3-item subset against `LLM_PROVIDER=anthropic` on every PR (env-gated; needs ANTHROPIC_API_KEY in CI secrets — guard so CI without the secret runs the noop path and skips).
- README badge: "tutor eval: 4.3/5 (n=30)".

### H3 — Full Playwright e2e against the live stack

The D5 axe gate already runs. Extend the same Playwright suite to cover *behaviour* on the golden paths:

- Auth: register → login → email-verify → forgot/reset.
- Catalog → enrol → complete a lesson → take a quiz → see certificate + Open Badge.
- Instructor: create course → AI-draft an outline → publish → see analytics.
- Tutor: ask a question in an enrolled course → assert citations point at real lessons.
- Multi-modal ingest: paste a known YouTube URL → preview shows the expected modules → commit creates the draft course.

CI: `e2e.yml` workflow that brings up docker, seeds, runs the suite, uploads traces on failure.

### H4 — Live demo deployment

Choose one of: **Fly.io** (best Postgres+pgvector story), **Railway**, **Render**.

- Two services: `lumen-api` (FastAPI + Celery worker + beat) and `lumen-web` (Next.js).
- Postgres with `pgvector` enabled.
- Redis for Celery + cache.
- S3-compatible storage (Fly's Tigris, Railway's blob storage, or external Cloudflare R2).
- Demo seed: 3 published courses (one with quiz, one with AI-ingested content, one with the full AI tutor experience), one demo student account.
- Public URL with HTTPS, baked into the README.
- A 90-second Loom screencast covering the headline features.
- Cost cap: < $40 / month on the smallest tier; aggressive auto-shutdown on idle.

### H5 — README rewrite to position Lumen as the agentic-AI demo

Current README is the original Django prototype's README. Rewrite to:
- Open with the live-demo URL + a hero screenshot.
- "What this is" paragraph that frames Lumen as **an agentic-AI engineering signature project** — the live demo of how multi-agent systems + RAG + MCP + evals come together in a real product.
- "Architecture" diagram (ASCII or Mermaid) showing the agent layer, MCP surface, RAG path, eval loop.
- "How to run locally" — `docker compose up` flow.
- "Eval scores" — live numbers from the latest eval run.
- "Built by" — name, LinkedIn, GitHub, brief role pitch.
- Badges: build status, eval scores, MCP-server registry link (after Phase I).

### H6 — Security pass for production exposure

- All secrets via env (already largely true). Add a `.env.example` review pass.
- CORS lockdown for prod profile (no `localhost`).
- Refresh-token rotation alarm: if reuse-detection fires, an admin notification fires too.
- Production guard now also checks `LLM_PROVIDER != "noop"` (so we don't ship demo with the fake provider).
- Rate-limit metrics surfaced in `/admin/observability` (429s per endpoint per hour).
- `docs/security.md` updated to mention the LLM cost guard, eval pipeline.

### H7 — Background-job and AI-trace observability dashboard

- `/admin/observability` page rolls up:
  - Celery queue depths + recent task failures.
  - LLM call traces (last 50, click into a single call to see prompt/response/cost/latency).
  - Retrieval quality: per query, the chunks retrieved + similarity scores.
- Use OpenLLMetry (Traceloop's OSS OpenTelemetry layer for LLM calls) or Langfuse (self-hosted, OSS). Default to OpenLLMetry since it slots into the existing OTel setup from Phase F.

## 3. Phase I — Agentic-AI signature features

These are the resume-anchor items. Each one is a genuine engineering moat.

### I1 — Lumen MCP server (the centrepiece)

**Why this is the biggest portfolio signal.** MCP became the standard in 2026; 10k active servers; donated to Linux Foundation. A self-built MCP server for a real product is the single most credible "I work with agents at the protocol level" artifact.

- New package `apps/backend/app/mcp/` exposing Lumen's surface as MCP tools over stdio + HTTP.
- Tools to ship:
  - `list_courses(filter)` — read-only catalog query.
  - `get_course(slug)` — full course detail + syllabus.
  - `search_lesson_content(course_slug, query, top_k)` — wraps `embeddings_retrieval.find_relevant_chunks`.
  - `ask_tutor(course_slug, question)` — wraps the full RAG tutor pipeline.
  - `list_my_due_reviews()` — FSRS queue for the authenticated learner.
  - `grade_review_card(card_id, rating)` — submit a review.
  - `create_course_draft(brief)` — instructor-scoped; kicks off the AI authoring pipeline.
  - `ingest_url_to_draft(url, course_id?)` — multi-modal ingest.
  - `list_my_progress()` — enrolment + completion + mastery rollup.
- Auth via OAuth client-credentials (the MCP spec's recommended pattern for service-to-service).
- Published to the public MCP registry (`registry.modelcontextprotocol.io`) so anyone can install it with `claude mcp add lumen`.
- README has a "Use Lumen from Claude Desktop" section with the config snippet.
- E2E test: spin up Claude Code in a sub-process, point it at the MCP server, ask it to "list my courses" — assert the right tools fire.

### I2 — Multi-agent tutor (the orchestration moat)

The current Phase E1 tutor is single-shot RAG. Replace it with a **planner-orchestrator** that picks among specialised sub-agents per turn:

- **Planner** (the tutor's "front") reads the question, decides which tools to invoke. Uses Claude Sonnet 4.6 with structured tool-call output.
- **Sub-agents** (each a focused LLM call with its own system prompt + tools):
  - `retriever` — wraps Phase E0's RAG, returns chunks + citations.
  - `web_searcher` — uses an open web-search API (Brave or Tavily) for context outside the course; clearly labels web-sourced claims.
  - `code_runner` — sandboxed Python via a `pyodide` worker; for technical courses, runs short snippets and returns output.
  - `quiz_generator` — on-demand practice questions in the lesson's style.
  - `concept_explainer` — for "explain this differently" follow-ups.
- The orchestrator's loop: plan → call tools → synthesise → optionally re-plan if confidence is low. Hard-cap at 5 tool-call rounds per turn.
- Every step traced via OpenLLMetry (H7).
- Frontend: the tutor panel shows the agent's plan + which tools were called per turn ("Retrieved 4 chunks, ran code sandbox, generated 1 follow-up question"). This is the moat — *show how the agent thinks*.

### I3 — Self-critique authoring agent (the multi-step reasoning moat)

Phase E2 generates outlines + lesson bodies + quizzes in one shot. Replace with a critique-revise loop:

- Step 1 — Researcher: web-searches the topic, builds a context bundle.
- Step 2 — Outliner: drafts a course outline using the research.
- Step 3 — Critic: rates the outline 0–5 on (coverage, learning-arc, scope), flags weak spots.
- Step 4 — Reviser: if critic score < 4, revise the weak spots and loop (max 3 revisions).
- Step 5 — Lesson-drafter: for each lesson, draft body + quiz.
- Step 6 — Final critic: rates the full course; instructor sees the rating before accepting.

Each step's prompt + output stored as a `CourseDraftTrace` row so the instructor can replay the agent's reasoning. Frontend studio surface shows the trace with collapsible steps.

### I4 — Agent-trace observability surface (the "show your work" moat)

This is what makes the project legible to a recruiter who has 60 seconds. The dashboard at `/admin/observability` already (from H7) shows traces; add a learner-facing version:

- After every tutor turn, a "Show me how you got this" disclosure expands into the plan + tool-call log + retrieval scores + the final synthesis.
- After every AI-authoring draft, the instructor sees the full critique-revise chain.
- Both views render with Workbench tokens; mono for IDs + timings; tabular nums for token counts.

This single feature, done well, is the most legible "I built agents and you can *see* them think" portfolio shot.

### I5 — Personalized learning-path agent (cohort-quality differentiator)

- New surface `/dashboard/path`. Learner states a goal ("I want to be a backend engineer in 6 months").
- Path-builder agent: searches the catalog, picks ~8 courses respecting prerequisites (auto-detected from lesson-chunk similarity), sequences them by depth, schedules them respecting FSRS load.
- Output: a plan with milestones, weekly schedule, and a "what to do today" widget.
- Re-plans monthly based on progress + new courses added to the catalog.

## 4. Cuts deferred but listed (Phase J candidates)

These are good ideas that don't make this round but should be in the next backlog:
- Voice tutor (Whisper STT + tutor + OpenAI TTS). Cost-prohibitive at the demo's free tier; revisit when revenue exists.
- Slack / Discord bot via the MCP server.
- Computer-use agent for ingest fallback.
- xAPI / SCORM integration for enterprise procurement.
- Knowledge graph builder (cross-course prereq detection becomes interesting at >100 courses).
- White-label / multi-tenant SaaS (the original PRD non-goal; revisit when there's a paying tenant).

## 5. Build sequence

Phases run sequentially but items within a phase run in parallel where independent.

- **Phase H (production hardening) — ~7 commits.** Each H-item is independent (different files), so dispatch all in parallel.
- **Phase I (agentic features) — ~5 commits.** I1 (MCP) and I5 (learning path) are independent of I2/I3/I4. I2 depends on H7 (observability) landing first because the multi-agent tutor needs the trace infrastructure. I3 depends on I2's orchestrator pattern. I4 surfaces what I2 + I3 produce.

Optimal dispatch order:
1. H1, H2, H3, H6 in parallel (4 agents).
2. H4 (deploy), H5 (README), H7 (observability) after H1+H2 land (3 agents).
3. I1 (MCP) and I5 (learning path) in parallel (2 agents).
4. I2 (multi-agent tutor) after H7.
5. I3 (self-critique authoring) after I2.
6. I4 (trace surface) after I3.

## 6. Definition of done for the v2 chapter

A reasonable recruiter spending 2 minutes on the project gets:
- A live demo URL that works on first click.
- A 90-second Loom showing the agent thinking through a tutor question with the trace expanded.
- A README that opens with positioning, eval numbers, MCP install snippet.
- A `claude mcp add lumen` install command that works.
- An eval dashboard showing reproducible scores against a golden dataset.
- A clear list of which agentic patterns are implemented (planner-orchestrator, critique-revise loop, MCP).

Once those six are true, the project is the strongest single-repo argument for "ship me an agentic-AI offer."

## 7. Operator notes for the next session

- Start with: read this spec + the memory + the existing rebuild spec.
- Use autonomous-execution mode (see [[autonomous-execution-mode]]). Parallel agents work BUT don't use worktree isolation on this codebase — see [[worktree-gotchas]].
- The dev DB needs `pgvector` extension; the `pgvector/pgvector:pg17` image is already in compose (from Phase E0).
- LLM API keys go in `.env`: `ANTHROPIC_API_KEY` (preferred) or `OPENAI_API_KEY`. Operator must set them before any non-noop path will work.
- Deployment target (H4): the operator hasn't picked one yet. Recommend Fly.io for pgvector ergonomics; Railway is simpler if the operator prefers a single-dashboard experience. Ask the operator before committing.
- Cost guardrail (H1) is mandatory before flipping to a live demo — otherwise a single curious visitor's bad-actor loop could rack up real dollars.

## 8. Execution addendum (2026-05-22, locked at next-session kickoff)

Operator picked free-tier paths over the spec's defaults. Spec text above is preserved as the design intent; this addendum is the **operative truth** for the v2 execution.

- **H4 deploy target → free-tier stack, not Fly-only.** Vercel (Next.js) + Fly.io scale-to-zero (FastAPI + Celery worker) + Supabase (Postgres + pgvector, free 500 MB) + Upstash (Redis, free 10k cmds/day) + Cloudflare R2 (storage, free 10 GB). Steady-state cost target: **$0/mo idle**; pay only if the demo gets sustained traffic. Daily Celery digest runs as a GitHub-Actions cron because Fly idle suspends `celery beat`.
- **H1 / H2 / I2 / I3 LLM backend → Groq Llama 3.3 70B (free tier) via OpenAI-compatible endpoint.** No new provider code: Lumen's existing `OpenAIProvider` already accepts `api_base`. Env: `LLM_PROVIDER=openai` + `OPENAI_API_BASE=https://api.groq.com/openai/v1` + `OPENAI_API_KEY=<groq-key>` + `LLM_MODEL=llama-3.3-70b-versatile`. The Anthropic / OpenAI codepaths stay intact and tested; the spec's "prod default = anthropic" becomes "prod default = openai-compatible, configured for Groq."
- **Eval-as-judge (H2) runs on the same Groq Llama 3.3 70B.** Weaker than Claude as a judge but free + reproducible. README will surface this honestly ("eval judge: Llama 3.3 70B via Groq").
- **Portfolio positioning frame → "swappable LLM layer, demo runs Groq for $0, prod-ready for Anthropic/OpenAI."** Not "powered by Claude." This is more honest given what the live demo actually runs and a stronger engineering story (provider abstraction earns its keep when it's actually exercised across vendors).
- **Cost guard (H1) still mandatory** even with free LLM tier — Groq's free-tier RPM cap will throttle long before $$ becomes a problem, but the same meter table powers the admin observability surface and prevents footguns when the operator later flips to paid Anthropic for production.
