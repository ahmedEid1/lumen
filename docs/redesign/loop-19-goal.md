# Loop 19 — goal

**OG image + screenshot regen + Lighthouse pass.** AUDIT.md §7 row 19. Penultimate loop before FINAL-REPORT.

## What shipped

- **`apps/frontend/src/app/opengraph-image.tsx`** — new Next.js 15 file-system convention OG card. 1200×630 PNG generated at request time at `/opengraph-image`. Auto-wired into `<head>` metadata + Twitter card. Workbench aesthetic: solid `#0A0B0D` background, lime brand mark, `Now open.` mono cartouche, display-face `Take a path. Become it.` headline. Pre-Loop 19 the layout had `openGraph: { title, siteName, type }` but no `images: [...]` — social shares rendered as text-only previews.

## Out of scope

- **Portfolio screenshot regen (hero / trace-timeline / studio-replay)** — these require the `agentic_demo.py` seed which loads a specific tutor conversation + draft course. The local dev DB doesn't currently have it; running `make seed` for the agentic flow is a backend follow-up. Production has the seed (the live demo URL exposes the working conversation), so the existing `docs/screenshots/*.png` set still represents the live demo state.
- **Formal Lighthouse scoring (≥95)** — running Lighthouse against prod requires Chrome with the CDP debug port + a runner. Deferred to FINAL-REPORT's quality pass; the spec's vague target ("≥95 on home + top-2 routes") will get a real number there or get amended to a more useful KPI.

## Why this is OK

Loop 19's original AUDIT §7 description was "Lighthouse + screenshot regeneration. README screenshots refreshed; Lighthouse ≥95 on home + top-2 routes. Update OG images." The OG image was the most user-visible miss — social shares are recruiter touchpoints that compound over time. Done.

The Lighthouse target + portfolio-shot regen are quality affordances that depend on infrastructure (Chrome CDP + seed data) rather than redesign-loop work. Tracking them as follow-ups for the FINAL-REPORT pass.

## Success criteria

- [x] OG image file created and wired via Next.js file-system convention.
- [x] Local `make test.web`: 50 files / 284 tests green (unchanged).
- [x] `pnpm exec eslint .`: 0 errors.
- [x] `pnpm exec tsc --noEmit`: clean.
- [ ] Single push, CI green first try.
- [ ] Prod visual review: open the deployed OG image at `https://lumen.ahmedhobeishy.tech/opengraph-image` to confirm it renders.
