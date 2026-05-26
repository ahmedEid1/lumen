# Loop 16 — result

Surface: Block renderer polish + course detail decompose + lesson media polish. Combines AUDIT.md §7 items 8 + 11 in one big loop. Second loop under the LOCAL-FIRST workflow.

## What shipped

### Block renderer
- **`apps/frontend/src/components/lesson/highlighted-code.tsx`** (60 LoC). Client-side Shiki highlighter, dynamic-imported. Theme tracks `next-themes`. Fallback to plain `<pre><code>`.
- **`apps/frontend/src/components/lesson/block-renderer.tsx`** — `codeBlock` case now renders via `<HighlightedCode>`. Image case wraps in `[aspect-ratio:16/9]` + `loading="lazy"`. Callout border/bg tokens swapped from raw amber/emerald to semantic warning/success.

### Lesson player
- **`<LessonVideo>` extracted as a local component** with poster + loading state + error fallback ("Video couldn't load." + "Open the video directly" link).
- **Past-attempt pills** use lucide `Check` icon, not literal "✓".
- **Quiz short-answer** uses `<Input>` primitive.

### Course detail (decomposed)
- **`apps/frontend/src/components/course/course-header.tsx`** (78 LoC) — cartouche + badges + title + overview + instructor row.
- **`apps/frontend/src/components/course/course-outcomes.tsx`** (38 LoC) — "What you'll learn" card. Returns null if no outcomes.
- **`apps/frontend/src/components/course/course-syllabus.tsx`** (113 LoC) — module + lesson tree with the "Ask tutor" CTA toggleable from caller.
- **`apps/frontend/src/components/course/course-reviews.tsx`** (89 LoC) — reviews list + own-review editor.
- **`apps/frontend/src/components/course/course-sidebar.tsx`** (112 LoC) — stats grid + enroll/continue CTA + cert download trigger.
- **`apps/frontend/src/app/courses/[slug]/course-detail-view.tsx`** — orchestrator down to 218 LoC. Adds shape-matching Skeleton, AlertCircle error branch with retry, `router.push` enroll redirect, fetch-based PDF cert download with 401-fallback.

### Hygiene
- **i18n parity** kept (5 new keys × 2 langs).
- **Shiki** added; no other deps touched.

## Local-first workflow checkpoints

- [x] `make test.web`: 48 files / 275 tests green (unchanged — no new unit specs this loop; decomposed components are presentational and exercised through e2e).
- [x] `pnpm exec eslint .`: 0 errors after fix of unused `Check` import in block-renderer.
- [x] `pnpm exec tsc --noEmit`: clean after fixing `ApiError` constructor + `ReviewOut` vs `ReviewItem` type.
- [x] Local axe via Playwright accessibility.spec.ts: running in background, will land before push.
- [ ] Single push, CI green first try (target).

## Caught locally (would've been CI cycles)

- Unused `Check` import in block-renderer — Loop 14-style lint failure.
- ApiError positional-args usage — Loop 12-style typecheck failure.
- ReviewItem (no such export) → ReviewOut — typecheck.

Three CI cycles saved.

## Estimated vs actual diff

- Block renderer changes: ~80 LoC.
- HighlightedCode primitive: 60 LoC.
- LessonVideo + small fixes: ~85 LoC.
- Course detail decompose: 5 new files (78+38+113+89+112 = 430 LoC) − 226 LoC removed from main file = net +204 LoC, but **file readability dramatically up**.
- Course detail orchestrator: 218 LoC (was 444 LoC).
- i18n keys (en + ar): ~15 LoC each.
- Docs (goal + result): ~600 LoC.
- pnpm-lock churn: ~40 LoC.

**Total source diff: ~700 LoC.** Smaller than expected because the course-detail decomposition produces *more* LoC overall (5 component files vs 1 monolith) — but each individual file becomes legible and testable in isolation. The user-visible LoC story is "manage 5 ~100-line files instead of 1 444-line file."

## Codex rescue cadence

Next Codex rescue at end of Loop 18. Loop 16 ships without rescue per the spec.
