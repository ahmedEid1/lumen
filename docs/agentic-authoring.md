# Agentic authoring — operator guide (Lumen v2 Phase I3)

This document explains the self-critique authoring agent that powers
`POST /api/v1/studio/ai/draft-course` and the studio reasoning-trace
viewer at `/studio/draft/{courseId}`.

If you are looking for the single-shot generators (the original
Phase E2 `/ai/outline`, `/ai/lesson-body`, `/ai/quiz` endpoints), they
are still wired and unchanged — this document covers the *multi-step*
authoring path that landed alongside.

## The loop in one diagram

```
brief
  │
  ▼
Researcher (Tavily snippets + catalog neighbours, NO LLM call)
  │   trace step: "researcher"
  ▼
Outliner (LLM)                                           ┐
  │   trace step: "outliner"                             │
  ▼                                                      │
Critic (LLM) — rates coverage / learning_arc / scope     │  outline phase
  │   trace step: "critic"                               │  capped at 6
  ├── mean ≥ 4.0 → accept ────────────────────┐          │  LLM calls.
  │                                            │          │
  ▼                                            │          │
Reviser (LLM)                                  │          │
  │   trace step: "reviser"                    │          │
  │                                            │          │
  └── loop back to Critic, max 3 revisions  ───┤          │
                                               ▼          ┘
                                          Persist course
                                          (draft status)
                                               │
                                               ▼
                                  Lesson-drafter (LLM × N lessons)
                                          trace step: "lesson_drafter"
                                          (uses ai_authoring.generate_lesson_body
                                           + .generate_quiz under the hood)
                                               │
                                               ▼
                                  Final critic (LLM)
                                          trace step: "final_critic"
                                               │
                                               ▼
                                          Return OrchestratorResult
                                          (course_id + final_score + draft_id)
```

Every step writes one `course_draft_traces` row. The instructor sees
the chain at `/studio/draft/{course_id}` — same data, vertical
timeline, expandable per-step payloads.

## Hard caps

| Cap                             | Value                           | Why |
| ------------------------------- | ------------------------------- | --- |
| Max revisions per draft         | `MAX_REVISIONS = 3`             | Past 3 the loop is either fighting the prompt or the model and burning more rounds won't help. |
| Max outline-phase LLM calls     | `MAX_OUTLINE_PHASE_LLM_CALLS=6` | Degrades cleanly if the critic never converges; the orchestrator accepts whatever outline it last had. |
| Critic acceptance threshold     | `ACCEPTANCE_MEAN_SCORE = 4.0`   | 4.0/5 is "no obvious gaps" in hand-graded outlines. Below that → reviser. |
| Rate limit on `/draft-course`   | 5/minute per user (shared with the existing `/ai/*` bucket) | One full draft burns up to `6 + 2·N_lessons + 1` LLM calls; 5/minute is already extremely generous. |

These constants live in `apps/backend/app/services/authoring_orchestrator.py`.

## Costs

A typical draft (4 modules, 12 lessons, 1 revision):

- Outline phase: outliner (1) + critic (2) + reviser (1) = 4 LLM calls.
- Lesson drafter: 12 lessons × 1 call each = 12 LLM calls.
- Final critic: 1 call.

**Total: ~17 LLM calls per draft.** With Groq's free Llama 3.3 70B
that's $0; with Claude Sonnet 4.6 at the documented pricing in
`app/services/llm_pricing.py` it's a couple of cents per draft.

The H1 cost meter records every call with one of the feature slugs:

- `authoring.outliner`
- `authoring.critic`
- `authoring.reviser`
- `authoring.lesson` / `authoring.quiz` (per-lesson calls bubble up through `ai_authoring.generate_lesson_body` / `.generate_quiz`)
- `authoring.final_critic`

The admin observability page rolls cost up by feature so the
operator can see "how much did the self-critique loop cost this
month" without join gymnastics.

## Environment

No new env vars. The orchestrator reuses:

- `LLM_PROVIDER` / `LLM_MODEL` / `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) — the same LLM provider every other agentic surface uses.
- `TAVILY_API_KEY` (optional) — when set, the researcher pulls 5-8 web snippets; when unset, the researcher's web phase is a graceful no-op (returns an empty snippet list with a note) and only the catalog-neighbour query runs.
- `EMBEDDING_PROVIDER` — the catalog-neighbour query uses embeddings; on the noop provider the query falls back to "most recently published" courses (same fallback as I5's `_condense_catalog`).

`LLM_PROVIDER=noop` produces a deterministic non-LLM response for
every step. Useful for CI / smoke testing the endpoint without
spending tokens.

## Failure modes and degradation

The orchestrator's contract is "**never raise to the API edge for
sub-agent failures** — only for truly catastrophic conditions
(brief empty, subject not found, outliner double-failure)." Concrete
behaviours:

| Failure                         | What the orchestrator does |
| ------------------------------- | -------------------------- |
| Empty brief                     | `AppError(authoring.brief_empty)` → 422 |
| Unknown `subject_slug`          | `NotFoundError(authoring.subject_not_found)` → 404, **no LLM call burned** |
| Outliner returns malformed JSON twice | `AppError(authoring.outliner_failed)` → 502 |
| Critic returns malformed JSON twice | Accept the current outline + log a warning, exit the loop |
| Reviser returns malformed JSON twice | Accept the previous outline + log a warning trace, exit the loop |
| Per-lesson body/quiz LLM fails | Placeholder lesson content (same shape as the E2 commit_outline placeholder) — the instructor sees "Draft — replace before publishing" in the lesson body |
| Final critic returns malformed JSON twice | Synthesise a neutral 3/3/3 score with an operator-visible note in the rationale |
| Tavily unset or HTTP failure   | Researcher's web phase no-ops; catalog-neighbour phase still runs |
| Embedding provider error       | Catalog-neighbour phase returns `[]`; the outliner still gets the web snippets |
| `course_draft_traces` INSERT fails | SAVEPOINT-isolated; the orchestrator continues with no trace recorded |

The "accept whatever we have" failure modes are deliberate — one
malformed reply mid-loop should produce a slightly-worse course, not
no course.

## The publish-anyway escape hatch

The studio surface always shows a **Publish anyway** button next to
the final critic's score. Agent suggests; instructor decides.

The button doesn't bypass any other constraint — the existing
`Courses.patch({status: "published"})` validation still runs
(must-have-lesson, owner-only, etc.). It only skips the soft
gate the critic's score might imply.

This is the deliberate trade-off: the model can be wrong, the
instructor's judgment is final.

## Trace shape

The studio viewer reads `GET /api/v1/studio/drafts/{course_id}/trace`
which returns the rows for the *most recent draft tied to this course*
in `step_index` order. Each row's `payload` is a JSONB blob the
frontend renders by convention:

| step              | payload fields                                              |
| ----------------- | ----------------------------------------------------------- |
| `researcher`      | `prompt_summary`, `response_summary`, `web_snippets[]`, `catalog_neighbours[]` |
| `outliner`        | `prompt_summary`, `response_summary`, `outline` (full struct) |
| `critic`          | `prompt_summary`, `response_summary`, `critic_scores`, `weak_spots`, `revision_number` |
| `reviser`         | `prompt_summary`, `response_summary`, `outline`, `revision_number` |
| `lesson_drafter`  | `prompt_summary`, `response_summary`, `lesson_id`, `lesson_type` |
| `final_critic`    | `prompt_summary`, `response_summary`, `critic_scores`, `weak_spots` |

The schema is "by convention" — the column is open-ended JSONB so
future step kinds can be added without a migration. The frontend
renderer (`draft-trace-timeline.tsx`) is defensive: it looks up
each key, falls back to "(none)" when missing, and never assumes
a particular shape.

## Where the code lives

| Concern                                       | File |
| --------------------------------------------- | ---- |
| Model + status constants                      | `apps/backend/app/models/course_draft_trace.py` |
| Migration (0026)                              | `apps/backend/alembic/versions/2026_07_13_0026-0026_course_draft_traces.py` |
| Orchestrator (main loop)                      | `apps/backend/app/services/authoring_orchestrator.py` |
| Researcher sub-agent                          | `apps/backend/app/services/authoring_subagents/researcher.py` |
| API endpoints (`/draft-course`, `/drafts/{id}/trace`) | `apps/backend/app/api/v1/ai_authoring.py` |
| Studio page                                   | `apps/frontend/src/app/studio/draft/[courseId]/page.tsx` |
| Trace timeline component                      | `apps/frontend/src/app/studio/draft/[courseId]/components/draft-trace-timeline.tsx` |
| API client                                    | `apps/frontend/src/lib/api/endpoints.ts` (`AI.draftCourse`, `AI.draftTrace`) |
| Tests (backend)                               | `apps/backend/tests/test_authoring_orchestrator.py`, `tests/test_authoring_trace_api.py` |
| Tests (frontend)                              | `apps/frontend/tests/studio-draft-trace.test.tsx` |

## Operator runbook for incidents

| Symptom                                                              | Likely cause / first check |
| -------------------------------------------------------------------- | -------------------------- |
| `/draft-course` returns 502 with `authoring.outliner_failed`         | LLM provider is offline OR producing unparseable JSON. Check the H1 admin observability page for two `error` rows tagged `authoring.outliner` in the last minute. |
| Drafts complete but the studio trace page is empty                  | Trace INSERTs SAVEPOINT-failed — check `course_draft_trace_persist_failed` log entries. The course itself is fine. |
| Researcher's `web_snippets` is always empty                          | `TAVILY_API_KEY` unset (intentional default) OR Tavily returned an error (look for `authoring_researcher_tavily_failed` warning). |
| All drafts hit the outline-phase cap                                | The critic is mis-calibrated for the prompts you're feeding. Inspect the trace; if the critic always scores ≤3, tighten the `_CRITIC_SYSTEM_PROMPT` and/or lower `ACCEPTANCE_MEAN_SCORE`. |
| One instructor is racking up cost                                    | The H1 budget guard is on (`LLM_USER_BUDGET_24H_USD`). When the cap fires the next `/draft-course` call returns the standard `BudgetExceededError` (429). |
