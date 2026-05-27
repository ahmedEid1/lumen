# Loop 30 — `/case-study` long-form narrative

**Date:** 2026-05-27
**Scope:** Plan-v7 §L30. Long-form companion to `/eval` +
`/eval/methodology` — the operator's story of how Lumen got built,
what got skipped, and what changed mid-flight.

## What shipped

### Six-section narrative page

`apps/frontend/src/app/case-study/{page.tsx,case-study-view.tsx}`
(new). Mirrors the `/eval/methodology` layout (single column,
generous line-height, cartouche per section) so a recruiter
reading top-to-bottom sees a familiar voice:

1. **Origin** — expanded founding story (~150 words; the README
   opener is 80, this version layers in the AWS t4g.small / cost-
   ceiling-as-feature framing).
2. **Architecture** — inline SVG sketch (no chart library) showing
   user → Next.js → FastAPI → Celery / Postgres / Redis → LLM.
   Hand-drawn-on-napkin style; the goal is "make the relationships
   obvious" not "polished documentation diagram." Two-protocol
   summary in the body.
3. **Anatomy of one turn** — five numbered steps, each one a
   single sentence, walking from POST through phase-fence claim
   through orchestrator-emits-events through stream-tokens through
   terminal-and-WHERE-clause-refuses-to-overwrite-aborted. Ends
   with the sweep-beat backstop.
4. **Prompt iteration** — two failure modes, two rewrites. Refusal-
   rate numbers (18% → 3%, adversarial >90%) are illustrative
   targets, framed as the calibration story rather than measured
   live numbers (which would need a sealed run).
5. **What I did not use** — four entries (LangChain/LlamaIndex,
   fine-tuning, dedicated vector DB, LLM-as-judge for adversarial)
   with the why-not for each.
6. **Lessons** — three what-I'd-do-differently paragraphs. Eval-
   first, streaming-substrate-choice, defaults-default-to-off.

Footer routes to /demo + /eval + email-me.

### Architecture SVG sketch

Inline SVG, no chart library. Six rectangle nodes (user, Next.js,
FastAPI, Celery, Postgres, Redis, LLM) with arrows showing
data-flow direction. The LLM box is dashed (external) — visual
signal that the LLM provider is the swappable boundary. Single
`<title>` element via `role="img"` + `aria-label` describes the
graph for a screen-reader.

The sketch uses `currentColor` for all strokes, so it inherits the
theme's foreground color (works in dark + light + any future
theme without per-theme edits).

## i18n

40 new keys per locale (en + ar) under `caseStudy.*`. Parity test
gates the build.

## Tests

| Surface | Tests |
|---|---|
| Headline + 6 cartouches rendered | 1 |
| Architecture SVG with role=img + aria-label | 1 |
| Closing CTAs (/demo + /eval + mailto) | 1 |
| **L30 total** | **+3 new** |
| Frontend suite | 61 files / 329 tests green |

## What did NOT ship (deferred)

- **Inline worked-example component** shared with `/eval`. The
  L20.5 canonical question is referenced in the prompt-iteration
  section as text; the L29 hero replay already gives a recruiter
  the visual. Reusing a single primitive component across both
  surfaces is L31-followup polish.
- **Real measured numbers** for the prompt-iteration refusal
  rates (18% → 3% > 90%). These are illustrative; the methodology
  page is honest about what's measured vs not measured. A
  follow-up sealed run will give real numbers to swap in.
- **C4 component-diagram + sequence-diagram** as separate dedicated
  diagrams. The L30 architecture sketch combines the concerns at a
  napkin-level. Mermaid-style separate diagrams would be polish for
  L31 once a screencap is recorded.

## Verification

```
$ pnpm exec eslint src/app/case-study src/lib/i18n   # clean
$ pnpm exec tsc --noEmit --incremental false          # clean (40 new i18n keys parity-verified)
$ pnpm exec vitest run                                 # 61 / 329 green
```

## Files

**Frontend new:**
- `apps/frontend/src/app/case-study/page.tsx`
- `apps/frontend/src/app/case-study/case-study-view.tsx`
- `apps/frontend/tests/case-study-view.test.tsx`

**Frontend modified:**
- `apps/frontend/src/app/sitemap.ts` (+ `/case-study`)
- `apps/frontend/src/lib/i18n/messages/en.ts` (+40 keys)
- `apps/frontend/src/lib/i18n/messages/ar.ts` (+40 keys)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L30 row)
- `docs/post-redesign/loop-30.md` (this file)
- `CHANGELOG.md` (modified)

## Codex rescue note

The post-L28 Codex rescue is still in deferred state — the
Anthropic API was overloaded at attempt time and the rescue agent
returned `API Error: 529`. The diff through L30 will be reviewed
in one batch once API capacity recovers. The next attempt should
be after L31 so the rescue covers L26 → L31 in one sweep.

## Next loop

L31 — 90s screencap + per-route OG cards + README portfolio TL;DR
rewrite. The screencap is gated on `FEATURE_TUTOR_STREAMING=true`
in prod (needs the live SSE flow to capture); the OG cards + README
rewrite are independent.
