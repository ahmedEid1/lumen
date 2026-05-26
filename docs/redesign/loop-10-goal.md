# Loop 10 — goal

Foundation C, slice 1: **Dialog + Sheet primitives + migrate the tutor modal**.

## Why now

Loops 1–9 + the loop-7 followup hotfix are shipped. The largest remaining primitive backfill per AUDIT.md §2 is the overlay family — **Dialog, Sheet, Popover, DropdownMenu, Tooltip**. Five primitives in one loop blows the 2000-LoC soft cap once tests + migrations + visual-regression bless are folded in. Splitting:

- **Loop 10 (this one):** Dialog + Sheet + migrate the **tutor modal** in `course-detail-view.tsx` (highest a11y blast radius — no focus trap, no `aria-modal`, no Escape, no focus restore).
- **Loop 11 (next):** Popover + DropdownMenu + Tooltip + migrate notifications-bell, locale-switcher, ai-outline-modal, ingest-modal, onboarding-tour, mobile menu.

Sheet rides along with Dialog this loop because it's literally a `side`-variant of the same Radix Dialog primitive — the cost is one extra component file + a `cva` variant matrix, not a separate Radix install.

## What "done" looks like

1. `apps/frontend/src/components/ui/dialog.tsx` — Radix-backed Dialog, Workbench-styled:
   - `<Dialog>`, `<DialogTrigger>`, `<DialogContent>`, `<DialogHeader>`, `<DialogFooter>`, `<DialogTitle>`, `<DialogDescription>`, `<DialogClose>`.
   - Focus trap, `aria-modal`, `role="dialog"`, Escape closes, click-outside closes, focus restore on close — all from Radix defaults.
   - Border-elevation visual (no shadow), Workbench surface ramp, lime-on-overlay accent.
2. `apps/frontend/src/components/ui/sheet.tsx` — Dialog with `side="right|left|top|bottom"`:
   - Same surface + a11y guarantees as Dialog; differs only in slide-in animation direction and content sizing (full-height for left/right, full-width for top/bottom).
3. **Tutor modal migration** in `course-detail-view.tsx` lines 417-441:
   - Replace hand-rolled `fixed inset-0` overlay with `<Dialog>` + `<DialogContent>`.
   - Tutor button becomes a `<DialogTrigger asChild>`.
   - Tutor panel renders inside `<DialogContent>`.
   - All current behaviour preserved: click-outside closes, X close button, height ~80vh.
4. **Unit tests** in `apps/frontend/tests/dialog.test.tsx`:
   - Render + open + ESC closes + click-outside closes + DialogClose closes + focus moves into Dialog when opened + `role="dialog"` + `aria-modal="true"`.
   - Sheet renders with each `side` variant.
5. **Visual-regression**: the tutor modal screenshot baseline updates if the chrome changes; otherwise no diff (the migration aims for visual parity by default, only adding a backdrop layer).
6. `make test.web` green.
7. STATUS.md row + `loop-10-result.md` retrospective.
8. CHANGELOG entry.

## Out of scope

- Popover, DropdownMenu, Tooltip primitives → Loop 11.
- Migrating ai-outline-modal, ingest-modal, onboarding-tour, mobile menu, notifications-bell, locale-switcher, profile delete-confirm → Loop 11.
- Tutor streaming SSE → Loop 14 (provisional, depends on backend SSE story).
- The tutor's own internal a11y (`aria-live`, focus management on open) → that's a Tutor-specific loop, not the Dialog primitive's job.

## Success criteria (binary)

- [ ] Dialog primitive ships, with displayName-attributable subcomponents and Radix focus-trap inheritance.
- [ ] Sheet primitive ships with 4-side variant.
- [ ] Tutor modal closes on ESC.
- [ ] Tutor modal restores focus to the "Ask Tutor" button on close.
- [ ] Tutor modal has `role="dialog"` + `aria-modal="true"` in the DOM.
- [ ] Dialog has a focus trap (tab cycles inside).
- [ ] `make test.web`: green.
- [ ] CI 5 gates: green (Backend, Frontend, E2E, Build container images, Accessibility).
- [ ] Visual regression: no unexpected diffs on the 16 baselines; tutor-modal screenshot blessed if changed.
- [ ] Prod deploy + visual review pass.
