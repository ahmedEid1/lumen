# Loop 16 — goal

**Block renderer + course detail polish** — combines AUDIT.md §7 items 8 (block renderer + lesson media) and 11 (course detail decompose + state coverage) into one team-day-sized loop.

Local-first workflow (per Loop 15's success).

## Why now

- Foundations A-E + Auth polish done. Learner-facing UI quality is the next priority — block renderer is what every enrolled student sees on every text lesson.
- AUDIT §3 Block renderer: "code blocks render in **plain text** — single most visible 'feels unfinished' hit." For an engineering-focused e-learning product, this is table stakes.
- AUDIT §3 Course detail: monolithic 444-LoC `course-detail-view.tsx`, `null`-on-load flash, no skeleton, no error recovery, `window.location.href` enroll redirect, raw PDF cert link.

## What "done" looks like

### Block renderer
1. **Shiki syntax highlighting** for code blocks. Theme via Shiki's `bundledThemes.github-dark` + a light theme variant; loaded client-side via `<HighlightedCode>` component.
2. **NextImage migration** for lesson images. Aspect-ratio reservation + `<Skeleton>` while loading. No more CLS on image lessons.
3. **Video poster + buffering + 403 fallback.** Today: `<video src=...>` with no chrome. After: explicit `poster` attr, loading spinner during buffer, error UI if MinIO URL 401/403s.
4. **Past-attempt pills:** literal `"✓"` → lucide `Check` icon.
5. **Quiz short-answer:** raw `<input>` → `<Input>` primitive.
6. **Callout token-drift fix:** `border-amber-500/40 bg-amber-500/10` etc. → semantic `warning` / `success` tokens (the `info` callout is fine — already on `--border` / `--muted`).

### Course detail
7. **Decompose:** extract `<CourseOutcomes>`, `<CourseSyllabus>`, `<CourseReviews>` as local components in the same file (or new files under `src/components/course/`).
8. **Skeleton matching populated layout:** the current "Loading…" string → shape-matched Skeleton (badge row + headline + grid stats + syllabus rows).
9. **Error branch with recovery:** "Course not found" gets a "Browse catalog" `<LinkButton>` + retry option.
10. **Unauthenticated enroll → `router.push`:** currently `window.location.href = "/login?next=..."`. Replace with `useRouter().push(...)`.
11. **PDF cert link: auth-error fallback.** Bare `<a href="/api/v1/.../cert.pdf">` today renders raw JSON if logged out. Wrap with a fetch-then-download pattern that redirects to login on 401.

## Out of scope

- Tutor streaming (separate big loop).
- Block editor changes (this is renderer only).
- Lesson player layout overhaul (Loop 18 = mobile/tablet).
- /admin/observability charts.
- Mastery / path viz (next loop or two).

## Success criteria

- [ ] Shiki highlights code blocks (dark + light themes).
- [ ] Lesson images: NextImage + reserved aspect ratio + skeleton.
- [ ] Lesson video: poster + buffering UI + error fallback.
- [ ] Past-attempt pills use lucide.
- [ ] Quiz short-answer uses `<Input>`.
- [ ] Callout uses semantic tokens.
- [ ] Course detail decomposed.
- [ ] Course detail skeleton + error recovery.
- [ ] Course detail unauth-enroll uses `router.push`.
- [ ] PDF cert has auth-error fallback.
- [ ] **Local verification clean** (lint + tsc + tests + dev-browser walk + axe).
- [ ] Single push, CI green first try.
- [ ] Prod visual review (including auth-gated as enrolled student) shows highlighted code.
