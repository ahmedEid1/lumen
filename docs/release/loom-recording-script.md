# Loom recording script — Lumen 1.1.0-agentic 90-second walkthrough

**Goal:** 90 seconds, 6 beats × 15 seconds, recorded against the local Docker stack while the Oracle deploy is still pending. The voiceover acknowledges "this is running locally" up-front; the URL bar will show `localhost:3000` instead of `lumen.ahmedhobeishy.de`. Recruiters care about the **agentic-AI behavior**, not the hostname — what makes Lumen interesting is the multi-agent tutor, the trace surfaces, and the self-critique authoring loop, all of which render identically locally.

This is the cleanest path: record once now, swap the URL banner in the README, and re-record if/when Oracle (or a Hetzner box) gives us a real public URL.

---

## Pre-recording checklist (15 min, do once)

### Local stack ready

```bash
docker compose up -d
# wait for healthchecks
curl http://localhost:8000/api/v1/health/live   # → 200
make migrate
make seed       # base seed
# the A5 agentic_demo seed runs automatically as part of `make seed` — see apps/backend/app/seeds/agentic_demo.py
```

Verify the seed worked:

- `http://localhost:3000` → landing page renders
- Log in as `student@lumen.test` / `Learn!2026` → dashboard shows 2 enrollments (FastAPI 100%, Data Engineering ~50%)
- Open the FastAPI course → tutor surface shows 1 seeded turn with agent trace
- Log in as `teacher@lumen.test` / `Teach!2026` → studio shows `AI Tutor Design Patterns` draft

### Recording environment

- **Browser:** fresh Chrome window at **1440×900** (use the Window > Set Size shortcut or just resize)
- **Loom desktop app** preferred over the browser extension (cleaner cursor, system audio mute, no overlays)
- **Audio:** use a headset or wired earbuds with mic; quiet room; do a 5-second test clip first
- **Tabs to pre-open** (in this order so you can Cmd+1, Cmd+2, ... between them):
  1. `http://localhost:3000` (landing — student logged out)
  2. `http://localhost:3000/catalog` (catalog browse)
  3. `http://localhost:3000/dashboard/tutor/<fastapi-course-cid>/turn/<seeded-message-id>` (Surface A — bookmark the actual URL by opening the page first)
  4. `http://localhost:3000/studio/draft/<ai-tutor-design-patterns-id>/replay` (Surface B)
  5. `http://localhost:3000/admin/observability` (admin obs — log in as admin first)
- **Hide bookmarks bar** (Cmd+Shift+B) and **close other tabs** so the only thing on screen is the demo
- **Mute system notifications** for the duration

### One-take vs multi-take

Loom supports trim + re-record on segments. Plan a **single 90-second take**. If you flub one beat, restart — re-shoots tend to take 4–6 attempts to get clean. Total time budget: ~20 min including retries.

---

## The 90-second script

**(0:00–0:15) Beat 1 — Intro + honest URL caveat**

> *(localhost:3000 landing page on screen)*
>
> "This is **Lumen** — an open-source agentic-AI learning platform I built as a portfolio piece. You're looking at it running locally on my laptop; the public demo at `lumen.ahmedhobeishy.de` is being provisioned. The agentic behavior is what matters — let me show you."

**(0:15–0:30) Beat 2 — Log in, open the tutor**

> *(Tab 2 → click "Sign in", paste `student@lumen.test` + `Learn!2026`, Enter)*
> *(Land on dashboard, click "Continue learning" on the FastAPI course)*
> *(Click the tutor icon / "Ask the tutor" button)*
>
> "Logging in as a student. Open the FastAPI course — every learner has a course-scoped tutor. The tutor answers using retrieval-augmented generation over the actual lesson content; every claim is cited back to a specific lesson chunk."

**(0:30–0:45) Beat 3 — Agent reasoning panel**

> *(The seeded turn shows up; click the `AgentReasoningPanel` chevron to expand)*
>
> "When the answer renders, this **Agent Reasoning Panel** shows the planner-orchestrator's plan and which tools fired. Lumen's tutor isn't one LLM call — it's a planner over five sub-agents: retriever, web-searcher, code-runner, quiz-generator, concept-explainer. You can see exactly what fired and what each returned."

**(0:45–1:00) Beat 4 — Observable trace surface**

> *(Switch to Tab 3 — pre-loaded `/dashboard/tutor/<cid>/turn/<mid>`)*
>
> "Every turn writes a full observable trace — token usage, USD cost, latency, the planner's tool-call log, and a retrieval audit of every chunk consulted. This isn't reverse-engineered from logs; the orchestrator emits it as a first-class artifact."

**(1:00–1:15) Beat 5 — Self-critique authoring**

> *(Switch to Tab 4 — `/studio/draft/<id>/replay`)*
>
> "The instructor side has an equivalent surface for the **self-critique authoring** loop: researcher → outliner → critic → reviser → lesson-drafter → final-critic. You can replay each step, see what the critic flagged, see what the reviser changed. Course drafts come out reviewer-ready because the critic already caught what a human would."

**(1:15–1:30) Beat 6 — Production observability + wrap**

> *(Switch to Tab 5 — `/admin/observability`)*
>
> "And it all flows through a per-user cost meter with hard budget guards — production-grade observability from day one. The MCP server is in the public registry; the eval harness ships in the repo. Links are below — I'd love to chat about agentic-AI engineering work."

---

## Voiceover delivery notes

- **Pace:** ~140 words/minute. The script above is ~190 words ÷ 90s = 127 wpm — comfortable.
- **Energy:** enthusiastic but not theatrical. Pretend you're explaining this to a friend who works at an AI company.
- **Pause for visual changes:** 0.5s after each tab switch before you start talking again. Lets the viewer's eye catch up.
- **The honest caveat in beat 1 is a feature, not a bug.** Acknowledging "running locally because the public demo is being provisioned" is more authentic than hiding the URL bar — recruiters appreciate engineers who say what's real.

---

## After recording

1. **Trim** the front and back in Loom (remove "OK, recording started..." and "...done"). Aim for exactly 90 seconds.
2. **Copy the Loom URL** (e.g. `https://www.loom.com/share/abc123def456`)
3. **Ping the orchestrator** with the URL. I'll paste it into the README's `LOOM_URL_TBD` placeholder and commit.
4. **Optional polish:** add chapter markers in Loom (`0:15 Tutor`, `0:30 Agent reasoning`, `0:45 Trace`, `1:00 Authoring`, `1:15 Observability`) so reviewers can jump.

---

## If you want to re-record once Oracle/Hetzner is live

The script above works identically with the live URL. Just:

- Replace `localhost:3000` with `lumen.ahmedhobeishy.de` in the pre-recording tab list
- Drop the "running locally; public demo being provisioned" caveat from Beat 1 (or swap to "this is the live demo at lumen.ahmedhobeishy.de")
- Re-record using the same beats
- New Loom URL replaces the old one in README

Don't gate the portfolio on re-recording. The local-stack Loom is **good enough to send applications today**.
