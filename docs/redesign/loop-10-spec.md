# Loop 10 — spec

Selected option: **C** (Dialog + Sheet primitives + tutor-modal migration). See `loop-10-options.md` §Decision.

## Files touched

### New
- `apps/frontend/src/components/ui/dialog.tsx` — Workbench Dialog (Radix Dialog backing).
- `apps/frontend/src/components/ui/sheet.tsx` — Workbench Sheet (Radix Dialog backing + `side` variant via `cva`).
- `apps/frontend/tests/dialog.test.tsx` — Dialog + Sheet unit coverage.
- `docs/redesign/loop-10-goal.md`, `loop-10-options.md`, `loop-10-spec.md`, `loop-10-result.md`.

### Edited
- `apps/frontend/src/app/courses/[slug]/course-detail-view.tsx` — replace lines 417-441 (hand-rolled tutor overlay) with `<Dialog>` chain.
- `apps/frontend/package.json` — add `@radix-ui/react-dialog`.
- `apps/frontend/pnpm-lock.yaml` — regenerated.
- `docs/redesign/STATUS.md` — row for Loop 10; backfill `f04efc1` into the loop-7-followup row.
- `CHANGELOG.md` — `### Added (UI redesign loop 10)`.

## Dialog primitive — implementation notes

- Built on `@radix-ui/react-dialog`. Re-exports `Root`, `Trigger`, `Portal`, `Overlay`, `Content`, `Title`, `Description`, `Close` under Workbench names.
- `<DialogContent>` composition (Radix `Content` + `Overlay` + `Portal`):
  - Portal mounts to `document.body` (avoids stacking-context issues with the existing `z-30/40/50` magic numbers in site-header/notifications-bell/learn page).
  - Overlay: `fixed inset-0 z-overlay bg-foreground/20 backdrop-blur-[2px]`.
  - Content positioning: `fixed left-1/2 top-1/2 z-modal -translate-x-1/2 -translate-y-1/2`.
  - Content surface: `bg-surface-2 border border-border rounded-lg p-6`.
  - Close button (top-right): `<DialogPrimitive.Close>` wrapping an X icon, `aria-label` from a `srLabel` prop (defaults to `t("dialog.close")`).
  - Workbench rule: no shadow. Border + opaque surface + the dimmed body backdrop do all elevation work.
- Z-index sourced from the Loop 1 ramp: `--z-overlay` for the backdrop, `--z-modal` for the panel. Tailwind utilities are `z-overlay` + `z-modal` (already aliased in `@theme inline`).
- Animation: Radix's `data-[state=open]:animate-in data-[state=closed]:animate-out` + Tailwind `fade-in-0`, `zoom-in-95`, `slide-in-from-bottom-2`. Uses `--duration-base` for timing (160ms — Workbench default).
- `DialogHeader`/`DialogFooter` are layout-only utility wrappers that match Workbench's spacing conventions (heading area gap-2 mb-4; footer gap-2 mt-6 justify-end).

## Sheet primitive — implementation notes

- Same Radix Dialog underpinning; differs in:
  - Content positioning: `fixed inset-y-0 right-0` (right side) / `inset-y-0 left-0` (left) / `inset-x-0 top-0` (top) / `inset-x-0 bottom-0` (bottom).
  - Content sizing: full-height for left/right (w-80 default); full-width for top/bottom (h-auto, max-h-80vh).
  - Slide-in animation matches side: `slide-in-from-right`, `slide-in-from-left`, `slide-in-from-top`, `slide-in-from-bottom`.
- `cva` variant: `side: "right" | "left" | "top" | "bottom"`, default `"right"`.
- Shares `DialogTitle` semantics via re-export — `SheetTitle` is `DialogPrimitive.Title` under the hood.

## Tutor modal migration

Before (`course-detail-view.tsx:417-441`):
```tsx
{tutorOpen && course.is_enrolled && (
  <div className="fixed inset-0 z-40 ... " onClick={...}>
    <div className="relative h-[80vh] w-full max-w-xl">
      <Button ... onClick={() => setTutorOpen(false)} aria-label={t("tutor.closeButton")}>
        <X className="h-4 w-4" />
      </Button>
      <TutorPanel courseId={course.id} />
    </div>
  </div>
)}
```

After:
```tsx
<Dialog open={tutorOpen && course.is_enrolled} onOpenChange={setTutorOpen}>
  <DialogContent
    className="h-[80vh] w-full max-w-xl p-0 overflow-hidden"
    srLabelClose={t("tutor.closeButton")}
  >
    <DialogTitle className="sr-only">{t("tutor.askButton")}</DialogTitle>
    <TutorPanel courseId={course.id} />
  </DialogContent>
</Dialog>
```

The "Ask Tutor" button (`course-detail-view.tsx:177-186`) does NOT wrap as a `DialogTrigger` because the Dialog's `open` is controlled by React state (`tutorOpen`); the Sparkles button's `onClick={() => setTutorOpen(true)}` stays put. Acceptable Radix pattern — `Dialog` is controlled by `open`/`onOpenChange` and `DialogTrigger` is optional sugar for the uncontrolled case.

`DialogTitle` is hidden via `sr-only` because the tutor panel ships its own visible heading; without `DialogTitle` Radix warns about missing accessible name. Same trick the lesson editor will use when its Dialogs land in Loop 11.

## Tests

`apps/frontend/tests/dialog.test.tsx` (~150 LoC):

1. **Renders trigger; opens on click.** Trigger button click → `screen.getByRole("dialog")` resolves.
2. **`aria-modal="true"`.** Open Dialog → asserts attribute.
3. **`role="dialog"`.** Open Dialog → asserts.
4. **Escape closes.** Open → keyDown ESC → role=dialog removed.
5. **Click-outside closes.** Open → click overlay → closed.
6. **`<DialogClose>` closes.** Open → click close → closed.
7. **Focus restore.** Trigger is focused → open → focus moves inside Dialog → close → trigger refocused. (happy-dom may have edge cases here — if so, the test asserts that close is called, and the prod Playwright walkthrough exercises full focus restore on real browsers.)
8. **Sheet renders with side variants.** Render `<Sheet open><SheetContent side="left">` etc. for each of 4 sides; assert `data-side` attribute.
9. **DialogTitle + DialogDescription render with correct semantics.** `role="heading"` test.

Keyboard focus-trap test is omitted — Radix's own test suite covers it, and happy-dom doesn't implement focus trap. The Playwright e2e suite + axe-core gate cover real-browser behaviour.

## Risks & mitigations

- **Z-index collision.** The existing notifications-bell uses `z-30/40/50`. Dialog uses the new ramp (`--z-overlay`, `--z-modal`). Verify in dev: open the tutor while the notifications popover is open. Should stack with Dialog above notifications. Mitigation: Loop 11 migrates notifications-bell to Popover, which uses the same ramp — collision goes away.
- **VR baseline drift.** The new Dialog has a `backdrop-blur-[2px]` overlay; the hand-rolled overlay had `bg-foreground/20` only. Tutor modal screenshot will diff. Re-bless once, confirm visually, commit baseline.
- **Tutor modal `srLabelClose` and the existing X button.** The hand-rolled X button was the close affordance. Now Radix renders its own `DialogClose` X. Verify: only ONE X visible. Mitigation: pass `p-0 overflow-hidden` on DialogContent to let TutorPanel control its own padding; close X sits at `absolute right-4 top-4` per Workbench convention. Tutor panel header has no X of its own.
- **Animation jank in tests.** Radix open animations + happy-dom — assert on the post-animation state via `findByRole`, not `getByRole`.

## Estimated diff

- New primitives: ~250 LoC (Dialog + Sheet + types).
- Tests: ~150 LoC.
- course-detail-view migration: -25 / +15 net -10 LoC.
- Loop docs (this file + goal + options + result): ~400 LoC (docs don't count toward soft cap by convention).
- STATUS + CHANGELOG: ~10 LoC.
- pnpm-lock churn: ~30 LoC.

**Total source diff: ~400 LoC. Well under the 2000 LoC soft cap.**
