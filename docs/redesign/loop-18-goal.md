# Loop 18 — goal

**Cmd+K command palette + KBD primitive + Codex rescue #5** — AUDIT.md §7 row 18 + every-3rd-loop rescue anchor (15 → 18).

## Why now

- AUDIT §1: "A Workbench-density product mandates this; today completely absent." Linear/Raycast/Vercel-dashboard density isn't real without a command palette.
- KBD primitive is the only ★ low-gravity primitive still missing from the kit.
- Codex rescue cadence anchors at Loop 18.
- 4th loop under LOCAL-FIRST workflow.

## What "done" looks like

### Primitives
1. **`apps/frontend/src/components/ui/kbd.tsx`** — small bordered mono pill for keyboard hints. `<Kbd>Cmd</Kbd> <Kbd>K</Kbd>` reads as the conventional shortcut affordance.
2. **`apps/frontend/src/components/shared/command-palette.tsx`** — cmdk-backed palette inside our `<Dialog>`. Mounts globally; opens on Cmd/Ctrl+K. Sections:
   - **Navigate**: home, catalog, dashboard, reviews, mastery, path, profile (+ studio if instructor/admin, + admin if admin).
   - **Search courses**: type-as-you-go against the existing catalog search; show top 5 with course title + subject in the item.
   - **Theme**: toggle dark/light.
   - **Sign out** (when authenticated).

### Wiring
3. **`apps/frontend/src/app/layout.tsx`** — mount `<CommandPalette />` after the auth provider.
4. **`apps/frontend/src/components/shared/site-header.tsx`** — replace the search input on `lg+` with a Cmd+K trigger button (`Search courses…  ⌘K`) that opens the palette. Mobile keeps the current `<HeaderSearch>` form so non-keyboard users have an entry point.

### Tests
5. **`apps/frontend/tests/kbd.test.tsx`** — renders as `<kbd>` element with mono-uppercase chrome.
6. **`apps/frontend/tests/command-palette.test.tsx`** — Cmd+K opens the dialog, type filters items, Enter navigates (via `router.push` mock).

### Rescue
7. **Codex rescue #5** on Loops 16-18 diff. Address P1/P2 findings in-loop.

## Out of scope

- Backend course-search optimization. The palette uses the existing catalog endpoint; if perf is an issue, that's a backend follow-up.
- Per-course "jump to lesson" entries. Lesson-level search requires a different index; defer.
- Tutor "ask the agent" entry inside the palette. Tutor lives inside an enrolled course context; the palette is global.
- macOS-specific symbol detection (just use ⌘ + K — the platform-appropriate symbol is universally readable).
- Mobile/touch UX optimizations beyond keeping the existing `<HeaderSearch>` on small viewports.

## Success criteria

- [ ] KBD primitive ships with semantic `<kbd>` markup + Workbench mono chrome.
- [ ] CommandPalette opens on Cmd/Ctrl+K from any route.
- [ ] Palette has Navigate / Search / Theme / Sign-out sections.
- [ ] Course search returns results within ~200ms (existing endpoint).
- [ ] Enter on a navigate item routes correctly via `router.push`.
- [ ] Header shows the Cmd+K hint button on `lg+` viewports.
- [ ] Local verification clean (lint + tsc + tests + axe).
- [ ] Codex rescue #5 dispatched + findings addressed.
- [ ] Single push, CI green first try.
- [ ] Prod visual review shows the new header hint button.
