---
name: session-handoff
description: "Current state as of 2026-05-25 14:50 CEST — PR #6 + #7 merged into main; three real Groq eval numbers minted; only AWS deploy remains"
metadata:
  node_type: memory
  type: project
  originSessionId: c24e4fa7-d1d4-44eb-89ca-ea020c9a34f3
---

**As of 2026-05-25 ~14:50 CEST:** PR #6 (340 commits — Wave 1+2 + screencast + MCP publish + initial eval) and PR #7 (ingest eval follow-up) both merged into `main`. Three real Groq eval numbers committed. Only the AWS deploy remains as the unblocked thread.

## What's merged into main

- **PR #6** (merge commit `b17e46c`): 340 commits — Wave 1+2 + captioned screencast + MCP registry publish + eval truthing + Oracle/AWS bootstrap scaffolding
- **PR #7** (merge commit `8cee7c6`): ingest eval follow-up — n=10 Groq run added once #6's youtube-transcript-api fix was live in the runtime image

## Real Groq eval numbers (judge: Llama 3.3 70B via Groq's OpenAI-compat endpoint)

| Suite | n | Mean | Judged | Notes |
|-------|---|------|--------|-------|
| **authoring** | 10 | **3.85/5** | 10/10 | Headline portfolio number. Axes: coverage 4.0, scope 4.0, learning_arc 3.9, brief_fidelity 3.5. |
| tutor | 30 | 2.0/5 | 10/30 | Conservatively low — API image doesn't ship sentence-transformers, retrieval forced to noop embedder, 10 items hit the "refuse on empty retrieval" safety path, 20 skipped. |
| ingest | 10 | 0.83/5 | 4/10 | 6 upstream YouTube fetch failures (rate-limited cloud IPs etc.). The 4 judged exposed the v1 chunker's one-module-per-video behavior — known follow-up. |

Reports live under [`docs/eval/`](docs/eval/) with curated names.

## Groq setup (lives in .env)

```
LLM_PROVIDER=openai
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_API_KEY=gsk_*** (key name "lumen-eval", created 2026-05-25 via console.groq.com)
LLM_MODEL=llama-3.3-70b-versatile
```

docker-compose.yml's `x-api-env` anchor now pass-throughs `LLM_PROVIDER`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_LOCAL`, `EMBEDDING_MODEL_OPENAI`, `OPENAI_API_KEY`, `OPENAI_API_BASE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_API_BASE`, `NOTION_TOKEN` — operator can switch providers via .env alone.

## What's still blocked / queued

1. **AWS t4g.small deploy** — see [[aws-deployment-state]]. Operator needs to launch EC2 + run `scripts/aws-bootstrap.sh` + finish the deploy chain. The screencast + MCP publish + eval numbers don't block on this.
2. **Tutor eval with real embeddings** — install `sentence-transformers` in the API image (~1GB PyTorch deps; not done autonomously), or set `EMBEDDING_PROVIDER=openai` + a real OpenAI key. Either unlocks the tutor n=30 from its current noop-embedder-bounded 2.0/5.
3. **Ingest chapter detection** — v1 chunker emits one-module-per-video. Real follow-up; not blocking.
4. **Master merge** — explicitly deferred per user: "we will not go to legacy until we are fully done."
5. **Voiced Loom** — silent captioned walkthrough ships today as [`docs/screencast/walkthrough.mp4`](docs/screencast/walkthrough.mp4). Voiced version waits for a live URL.

## How to apply when re-entering

- `git log --oneline origin/main ^origin/legacy` shows everything queued for the legacy cut
- `docs/eval/README.md` lists every checked-in eval artifact + how to mint a new one
- `.env` already has the Groq config; `docker compose up -d --force-recreate api worker beat` brings it back live
- The MCP server is live: `io.github.ahmedEid1/lumen` at https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ahmedEid1%2Flumen

## Phase J / longer-horizon items still queued

Carry-over from the previous v2 spec — not blocked by the merges:
- Voice tutor (Whisper STT + tutor + TTS) — cost-prohibitive on free tier
- Slack / Discord bot via the MCP server — natural extension of I1
- Computer-use agent for ingest fallback when scrapers fail
- xAPI / SCORM integration for enterprise procurement story
- Knowledge graph builder (cross-course prereq detection at >100 courses)
- White-label / multi-tenant SaaS — original PRD non-goal; revisit if there's a paying tenant
