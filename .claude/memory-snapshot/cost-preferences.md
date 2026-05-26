---
name: cost-preferences
description: "Operator strongly prefers free / near-zero-cost paths for infra and LLM backends — pick free-tier stacks over single hosts, swappable LLM layer over locked-in vendor"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 370d68d0-4084-445e-939d-10cfb54b9dc9
---

When choosing infra or LLM backends for this project, the operator strongly prefers free or near-zero-cost paths over the "recommended" paid option.

**Why:** Asked twice on 2026-05-22 — first "is any of [Fly/Railway/Render] free?", then "is there some very [cheap] option [for the LLM]?" — and on both rounds picked the free option once it was offered. Lumen is a portfolio project, not a revenue product, so spend on dev/demo infra should be near-zero unless there's a clear positioning reason to pay.

**How to apply:**
- When proposing infra options, lead with the free/free-tier path even if it has more moving parts. Frame the paid option as "more polished, monthly cost" rather than "recommended."
- For LLM backends, prefer **Groq's free tier (Llama 3.3 70B, OpenAI-compatible)** as the demo default. Lumen's existing `OpenAIProvider` already accepts `api_base`, so Groq drops in via `OPENAI_API_BASE=https://api.groq.com/openai/v1` + `OPENAI_API_KEY=<groq-key>` + `LLM_PROVIDER=openai` + `LLM_MODEL=llama-3.3-70b-versatile` with zero new code.
- **Decisions locked for v2 (2026-05-22):**
  - H4 deploy target: free-tier stack — Vercel (Next.js) + Fly.io scale-to-zero (FastAPI + worker) + Supabase (Postgres + pgvector, free 500MB) + Upstash (Redis, free 10k cmds/day) + Cloudflare R2 (storage, free 10GB).
  - LLM backend: Groq free tier (Llama 3.3 70B via OpenAI-compatible endpoint). Eval-as-judge runs on the same model. Anthropic/OpenAI code paths stay intact for future flip.
- Frame portfolio positioning as **"swappable LLM layer; demo runs Groq for $0, prod-ready for Anthropic/OpenAI"** rather than "powered by Claude" — this is more honest given what the live demo actually runs.

**Things to avoid:**
- Don't default to "$5-15/mo is basically free" reasoning — for this operator, $0 vs. $5 matters.
- Don't push Anthropic / OpenAI for tasks where Groq Llama 3.3 70B is good enough (tutor, eval judge, authoring agent). Reserve them for places where quality genuinely differentiates and the operator has signed off on spend.
