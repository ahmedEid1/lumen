# Loop 5 — Goal

**A focused first application sweep: replace one loading/empty surface with the loop-3 primitives, fix two raw-Tailwind-hue leaks that bypass the token system, and close the two i18n leaks the audit named.**

The audit catalogues a lot of surfaces that "would benefit" from Skeleton/EmptyState — but most of those routes (dashboard home, mastery, reviews, lesson player) are due for fuller redesigns in their own loops later. Spraying primitives across all of them now produces a 1500-LoC sweep that I'd partially undo when those routes get their proper polish loop. Loop 5 instead picks the changes where the primitive application is *terminal* — the cleanup ships and stays.

- **Surfaces:**
  - `apps/frontend/src/app/studio/page.tsx` — replace the `<p>Loading…</p>` line + the hand-rolled empty-state `<div className="surface …">` with `<Skeleton variant="card" />` and `<EmptyState icon title cta />`.
  - `apps/frontend/src/components/admin/evals/ScoreBadge.tsx` — replace `text-emerald-300 / amber-300 / rose-300` raw Tailwind hues with `text-success / warning / destructive` tokens.
  - `apps/frontend/src/components/admin/observability/LLMTracesTab.tsx` (`StatusBadge` inner component) — replace `bg-yellow-500/15 text-yellow-700 dark:text-yellow-400` with `bg-warning/15 text-warning`.
  - `apps/frontend/src/components/course/course-card.tsx` — wrap the two hardcoded English strings (`"Featured"` line 41, `"modules"` line 64) in `useT()` calls, adding the matching keys to `messages/en.ts` (+ Arabic parity required by `i18n-parity.test.ts`).

- **Persona:** every reviewer of the eval dashboard + every consumer of the studio empty state. Right now the eval scores read as a custom palette diverging from the rest of the app under light theme (the `text-emerald-300` hue was picked for dark mode; on light surfaces it's near-illegible). After this loop the badges read in the Workbench palette under both themes.

- **Binary success criteria:**
  1. `grep -E "text-emerald-300|text-amber-300|text-rose-300|text-yellow-700|text-yellow-400" apps/frontend/src/components` returns 0 matches.
  2. ScoreBadge tone mapping: `value ≥ 4` → `text-success`; `value ≥ 3` → `text-foreground`; `value ≥ 2` → `text-warning`; otherwise `text-destructive`. StatusBadge `throttled` → `text-warning`.
  3. `apps/frontend/src/app/studio/page.tsx:142` no longer contains `t("common.loading")` as bare paragraph text — replaced by 3 rows of `<Skeleton variant="card" className="h-16" />` matching the populated row shape.
  4. studio empty-state branch uses `<EmptyState icon={GraduationCap} title body cta />` instead of the hand-rolled `<div className="surface flex flex-col …">`.
  5. course-card.tsx imports `useT` and `course.is_featured && <Badge>{t("courseCard.featured")}</Badge>` + `{t("courseCard.modules")}` replace the two hardcoded strings.
  6. New i18n keys (`courseCard.featured`, `courseCard.modules`) added to `messages/en.ts` AND `messages/ar.ts` — the `i18n-parity.test.ts` regression will catch the mismatch otherwise.
  7. `make test.web` ≥ 36 files / 194 tests green (no new test file in this loop; just edits).
  8. Visual regression: 8 public baselines pass; the catalog baseline almost certainly re-blesses (course-card change) — re-bless and note in the result doc.
  9. STATUS.md row 5 + CHANGELOG `### Added (UI redesign loop 5)`.

Out of scope (deferred):
- Dashboard home loading skeletons — Loop 14 (Dashboard re-imagining) re-architects the whole surface.
- Mastery / reviews loading skeletons — Loop 9 (Mastery + Path viz) re-architects those.
- Lesson-player loading shape — Loop 16 (Lesson + tutor mobile/tablet pass) re-walks the whole player.
- Admin audit page filter + pagination — Loop 13 (Admin polish).
- Profile notif prefs Switch migration — Loop 5b (Form-input primitives) or a later loop.

This loop is deliberately small because it's the *first* application sweep — the foundation-tier loops shipped a lot of primitives, and the first real consumer should be a tight one so I can validate the API surface before scaling.
