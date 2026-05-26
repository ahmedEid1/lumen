# Loop 17 — result

Surface: Mastery viz + Path viz + RTL sweep. Third loop under LOCAL-FIRST workflow. Targets AUDIT.md §7 items 9 (mastery + path viz) and 17 (RTL sweep) — combined into one team-day loop.

## What shipped

### Mastery (`apps/frontend/src/app/dashboard/mastery/page.tsx`)
- Per-signal lucide icons on weak-spot pills — closes the audit's "colour-only meaning" finding. `XCircle` / `Clock` / `AlertCircle` / `MessageCircle` mapped to `quiz_failed` / `card_overdue` / `quiz_low` / `tutor_repeat`.
- 2-colour bars: completion stays `bg-primary` (lime); mastery now `[&>div]:bg-info` (info-blue from Loop 1's token).
- Shape-matching `<Skeleton variant="card">` rows replace the `h-32 animate-pulse` block placeholder.
- Dropped the `course_id.slice(0, 12)` debug ID from the course row header.

### Path (`apps/frontend/src/app/dashboard/path/components/MilestoneTable.tsx` + new helper)
- **`apps/frontend/src/lib/lesson/slug-to-title.ts`** (24 LoC) — pragmatic frontend-only fix for raw-slug-as-title. Doesn't need a backend change to `LearningPathStepOut`.
- MilestoneTable row now renders `slugToTitle(step.course_slug)` instead of `step.course_slug`.
- Dropped the `step.course_id.slice(0, 12)` debug span from the row header.
- Source-header `TODO(orchestrator)` comment trimmed.

### RTL sweep (4 of 4 leaks fixed)
- `apps/frontend/src/components/trace/TraceTimeline.tsx:146,152` — `left-3` → `start-3` (2 instances).
- `apps/frontend/src/app/studio/draft/[courseId]/components/draft-trace-timeline.tsx:83,86` — `left-3` → `start-3` (2 instances).
- `apps/frontend/src/components/trace/TraceStepCard.tsx:107` — `text-left` → `text-start`.
- `apps/frontend/src/components/tutor/agent-reasoning-panel.tsx:117` — `text-left` → `text-start`.
- AUDIT.md §4 cross-cutting #10 (RTL discipline) is now closed.

## Local-first verification

- [x] `make test.web`: 48 files / 275 tests green.
- [x] `pnpm exec eslint .`: 0 errors.
- [x] `pnpm exec tsc --noEmit`: clean.
- [ ] Local axe: TBD before push.
- [ ] Single push, CI green first try.

## What didn't ship

- Horizontal SVG week timeline for the path page. Decided not to ship a custom SVG without first validating with real users what the timeline orientation needs to show. The text-based MilestoneTable + slugToTitle fix gives the path page legibility now; a viz pass can come later (or with backend changes that add timestamps to each step).
- Inline-English → i18n key extraction for the path page. The audit calls it out, but moving the English strings into en + ar both adds ~30 keys × 2 files and forces every future copy tweak through the i18n loop. Deferred to a dedicated i18n-extraction loop.
- Mastery per-day activity heatmap. Backend doesn't ship a per-day series; this needs a backend follow-up to make sense.

## Estimated vs actual diff

- Mastery polish: ~30 LoC net (signal icons + bar tint + skeleton).
- Path polish: ~10 LoC net + new 24-LoC helper.
- RTL sweep: 4 single-char-replacement edits = ~4 LoC.
- Loop docs + STATUS + CHANGELOG: ~250 LoC.

**Total source diff: ~70 LoC** (excluding docs). Smaller than Loops 14-16 because the surface changes are precise micro-polish, not new primitives. Still substantial because each touches a high-traffic learner-facing surface.

## Codex rescue cadence

Next rescue at end of Loop 18 (every-3rd: 15 → 18). This loop ships without rescue.
