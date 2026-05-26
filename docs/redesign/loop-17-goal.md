# Loop 17 — goal

**Mastery viz + Path viz + RTL sweep** — combines AUDIT.md §7 items 9 + 17 + path-page debt cleanup. Third loop under LOCAL-FIRST workflow.

## Why now

- Mastery page today: "two thin Progress bars per course + a list of pills." Audit §3 calls this out as the page where the design promises analytics and ships none. Real spatial encoding is the gap.
- Path page today: inline English strings, literal `TODO(orchestrator)` in source, `MilestoneTable` renders `course_slug` as title, `course_id.slice(0,12)` debug leak visible to learners.
- RTL leaks (audit §4 cross-cutting #10): 4 known leaks in trace + tutor components that visually break under `dir="rtl"`.

## What "done" looks like

### Mastery viz
1. **Two-colour bars** — completion stays lime (`bg-primary`), mastery switches to a second accent (info blue or muted secondary) so the learner sees the distinction at a glance. Use `--info` token (already exists from Loop 1).
2. **Per-signal lucide icons** in weak-spot pills — `XCircle` for quiz_failed, `Clock` for card_overdue, `AlertCircle` for quiz_low, `MessageCircle` for tutor_repeat. Currently the signal communicates via colour-only (the audit's signal-severity finding).
3. **Shape-matching Skeleton** — the current `<div className="surface h-32 animate-pulse">` placeholders → proper Skeleton-variant rows matching the populated layout.
4. **Optional**: small per-course timeline strip (last 7 days × course = 7 dots) showing activity. Defer to a backend follow-up if data isn't shipped.

### Path viz
5. **Horizontal week timeline** — replace the current per-step Card grid with a horizontal SVG timeline showing milestones (week ranges) across the X axis with course cards stacked vertically per milestone. Custom SVG, no recharts.
6. **slug-as-title fix** — `slugToTitle` helper that turns `"data-structures-essentials"` → `"Data Structures Essentials"`. Imperfect (won't handle proper nouns) but better than raw slugs.
7. **Drop `course_id.slice(0,12)`** — the debug ID leak in MilestoneTable header.
8. **Drop the `TODO(orchestrator)` literal** from the source comment header. (Comment cleanup, not feature.)
9. **i18n: extract the inline English** path-page strings to en + ar. (Currently the comment admits this is deferred.)

### RTL sweep
10. `apps/frontend/src/components/trace/TraceTimeline.tsx:146,152` — `left-3` → `start-3`.
11. `apps/frontend/src/app/studio/draft/[courseId]/components/draft-trace-timeline.tsx:83,86` — `left-3` → `start-3`.
12. `apps/frontend/src/components/trace/TraceStepCard.tsx:107` — `text-left` → `text-start`.
13. `apps/frontend/src/components/tutor/agent-reasoning-panel.tsx:117` — `text-left` → `text-start`.

## Out of scope

- Backend changes to add `course_title` to LearningPathStepOut. The `slugToTitle` helper is the pragmatic fix this loop.
- Mastery per-day activity heatmap — requires a backend timeseries shape that doesn't exist yet.
- Cmd+K command palette → Loop 18.
- Lighthouse pass → Loop 19.
- Streaming tutor (audit §7 row 7) — biggest remaining loop, deferred to its own iteration.

## Success criteria

- [ ] Mastery: completion + mastery bars visually distinct.
- [ ] Mastery: lucide icons on weak-spot pills.
- [ ] Mastery: Skeleton matches populated row shape.
- [ ] Path: horizontal SVG milestone timeline.
- [ ] Path: titles render via slugToTitle (no more raw slugs).
- [ ] Path: debug ID slice removed from row.
- [ ] Path: TODO(orchestrator) literal removed from source.
- [ ] Path: i18n keys added for the inline English strings.
- [ ] 4 RTL leaks fixed (left-* → start-*, text-left → text-start).
- [ ] **Local verification clean** (lint, tsc, tests, axe).
- [ ] Single push, CI green first try.
- [ ] Auth-gated visual review shows new mastery + path renders for the student account.
