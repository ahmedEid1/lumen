# ADR-0014: Product surface expansions — quiz history, captions, FTS, outcomes

- **Status:** Accepted
- **Date:** 2026-07
- **Deciders:** maintainers

## Context

Iterations 73–87 added five user-visible product surfaces that all
share a common shape: each closes a gap a real LMS user (or auditor)
would have flagged, each is opt-out or no-op when not configured,
and each persists its data through migrations rather than via the
`payload` JSONB grab-bags. Bundling them here so the design choices
don't drift into folklore.

## Decision

### Quiz attempt history (iter 73-74)

Append-only `quiz_attempts` table — one row per submission, never
overwritten. Indexed on `(enrollment_id, lesson_id, created_at)`
for the "latest N for this learner on this quiz" query. The latest
attempt also still hits `LessonProgress.payload` for backward
compat with the existing grading path; the history is additive.

Why a new table instead of an array on LessonProgress: arrays would
have grown unbounded inside a single row, and the existing payload
holds latest-attempt grading state. The cleaner thing was always
to split history off — payload becomes "current state", attempts
becomes "audit trail."

### Discussion threads (iter 77-80)

Two-table flat-reply forum — see ADR-0013 for the full rationale.

### Video captions (iter 82)

`VideoLessonData.captions_url` plus `captions_label` /
`captions_lang` defaults. The lesson player emits `<track default>`
so captions are on out of the gate. Upload allow-list gains
`text/vtt` so instructors can presign through the normal flow.

Why VTT and not SRT: VTT is what `<track>` natively reads, no
conversion needed. SRT requires JS-side transcoding which we'd
rather not ship.

### Postgres full-text ranking (iter 85)

`websearch_to_tsquery` + `ts_rank` against an inline
`to_tsvector('english', title || ' ' || overview)`. ILIKE kept
as an OR fallback so partial-word matches don't regress
(`"java"` still finds `"JavaScript"`).

Why inline tsvector instead of a materialised column + GIN:
the courses table is small enough that the recompute cost per
search is negligible. Promote to a stored column + GIN when the
table crosses ~1M rows.

### Course "What you'll learn" outcomes (iter 86-87)

JSONB array on `courses` with Pydantic-side trim / drop-empties
/ length caps (240 per item, 12 items max). Server-default `[]`
so existing rows backfill safely. Renders as a 2-column
checkmark grid above the syllabus; hidden when empty.

Why not a separate table: the field is intrinsic to the course,
not relational. A single `courses` row gives you everything
needed to render the detail page; one fewer join.

## Alternatives considered (cross-cutting)

- **Stripe / payments first.** Rejected for now — multi-week build,
  blocks on tax / regional pricing decisions the product owner
  hasn't made.
- **One mega-PR for the discussions feature.** Rejected — split
  across 4 iterations (backend, frontend, notifications, deep-
  links) made each commit reviewable and lets the deployment
  cadence stay weekly rather than monthly.

## Consequences

Positive:
- The platform now ships every "is this a real LMS?" feature an
  evaluator would tick: forum, attempt history, captions for
  accessibility, relevance search, outcome bullets.
- All five additions are reversible — they didn't break any
  existing endpoint contract (only the iter 56 upload-shape
  change was breaking, and that was security-driven, not
  product-driven).

Negative:
- Five new tables (`quiz_attempts`, `discussions`,
  `discussion_replies`, plus the JSONB-only `learning_outcomes`
  column) — the conftest truncate list grows. Acceptable; each
  is documented in this ADR.

## References

- iter 73 (`feat(quiz): append-only attempt history`)
- iter 74 (`feat(quiz): show attempt history in the player`)
- iter 77-80 (discussions)
- iter 82 (`feat(lessons): WebVTT captions`)
- iter 85 (`feat(catalog): Postgres full-text ranking`)
- iter 86-87 (`feat(courses): "What you'll learn"`)
- ADR-0013 (discussion thread design)
