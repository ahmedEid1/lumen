# Loop 12 — spec

Selected option: **B** (Tooltip primitive + 4 modal migrations + Codex rescue #3).

## Files touched

### New
- `apps/frontend/src/components/ui/tooltip.tsx` — Workbench Tooltip.
- `apps/frontend/tests/tooltip.test.tsx`.
- `docs/redesign/loop-12-{goal,options,spec,result}.md`.
- `docs/redesign/codex-review-loops-10-to-12.md` — rescue digest.

### Edited
- `apps/frontend/src/components/shared/site-header.tsx` — wrap ThemeToggle in `<Tooltip>`. Wrap `LocaleSwitcher` and `NotificationsBell` triggers too (consistent header chrome).
- `apps/frontend/src/components/studio/ai-outline-modal.tsx` — strip the hand-rolled chrome + Escape listener; wrap content in `<Dialog>`.
- `apps/frontend/src/components/studio/ingest-modal.tsx` — same pattern.
- `apps/frontend/src/components/onboarding/onboarding-tour.tsx` — same pattern.
- `apps/frontend/src/app/profile/page.tsx` — convert inline-expand delete-confirm to `<Dialog>` with the password input + destructive confirm button + cancel.
- `apps/frontend/src/styles/globals.css` — add `data-wb-tooltip-content` animation rule (re-uses `fade-in` keyframe).
- `apps/frontend/package.json` + `pnpm-lock.yaml`.
- `docs/redesign/STATUS.md`, `CHANGELOG.md`.

### Possibly updated by Codex rescue
- Whatever Codex flags. Tracked in the rescue digest. Prefer fixing in this loop's commit; split off if it needs more than ~150 LoC.

## Tooltip primitive

```tsx
const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<...>(
  ({ className, sideOffset = 6, ...props }, ref) => (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        data-wb-tooltip-content=""
        className={cn(
          "z-tooltip rounded-md border border-border bg-card text-card-foreground",
          "px-2 py-1 font-mono text-[10px] uppercase tracking-wider",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  ),
);
```

- `TooltipProvider` wraps the app in `layout.tsx` (delayDuration={300}, skipDelayDuration={150}).
- Z-index `z-tooltip` (60 from Loop 1 ramp — sits above modals).
- Mono-caps text matches the Workbench cartouche pattern (same energy as `<Badge variant="muted">`).
- No arrow — Workbench rule: simple geometric shapes only.

## Modal migration template

The same diff shape applies to all 4. The key differences:

| Modal | maxWidth | Internal | Notes |
|---|---|---|---|
| ai-outline-modal | `max-w-3xl` | 3-phase state machine | preserve `data-testid="ai-outline-preview"` |
| ingest-modal | `max-w-3xl` | multi-step ingest | needs `open` prop preservation (caller passes `open` + `onClose`) |
| onboarding-tour | `max-w-2xl` | step state | smallest of the four; was already `role="dialog"` |
| profile delete | `max-w-md` | password input + cancel/confirm | convert from inline-expand to actual Dialog |

For ai-outline-modal + ingest-modal + onboarding-tour: callers control the open state via `tutorOpen`-style booleans. Each component currently takes `onClose: () => void` and renders unconditionally when mounted (parent gates via `{showModal && <Modal />}`). The migration leaves that gating in place — `<Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>` works for "render this modal whenever it's mounted, close-on-X via the parent callback".

For profile delete: the inline-expand pattern doesn't have a separate component — it's inline JSX. Migration extracts it into a `<DeleteAccountDialog>` local component inside `profile/page.tsx` (or keeps it inline as a `<Dialog>` block).

## Tooltip integration

- Wrap `<ThemeToggle>` button in `<Tooltip><TooltipTrigger asChild>… <TooltipContent>{t("header.themeToggle")}</TooltipContent></Tooltip>`.
- Wrap `<LocaleSwitcher>` trigger (the icon button inside `DropdownMenuTrigger`) — but Radix DropdownMenu's Trigger doesn't combine cleanly with Tooltip Trigger. **Decision: skip LocaleSwitcher tooltip this loop**; the trigger already has `aria-label` and the dropdown shows the locale label inline. Adding Tooltip here would conflict with the DropdownMenu's own focus management.
- Wrap `NotificationsBell` trigger — same concern with PopoverTrigger. **Decision: skip**.
- Theme toggle is the only consumer this loop.

## Tests

`apps/frontend/tests/tooltip.test.tsx` (~80 LoC, 4 tests):
1. Hover trigger → tooltip appears with `role="tooltip"` (use `userEvent.hover`).
2. Mouse out → tooltip disappears.
3. Focus trigger → tooltip appears (keyboard-focus parity).
4. `data-wb-tooltip-content` attribute set.

Note: happy-dom's pointer-event simulation is partial. If a hover assertion is flaky, prefer focus-based assertions which Radix supports identically.

For the modal migrations: existing tests in `ai-outline-modal.test.tsx`, `onboarding-tour.test.tsx`, and the studio integration spec should keep passing. Spot-check after each migration. If a test asserts on the old `role="dialog"` ancestor markup, Radix portals the content — `screen.findByRole("dialog")` still resolves but the ancestor chain differs.

## Risks

- **Radix Dialog + existing parent gating.** Most callers do `{open && <Modal onClose={() => setOpen(false)} />}`. With Dialog, `open` becomes a Radix prop; the parent still tracks state but the close callback is `onOpenChange`. Mitigation: callers stay unchanged; the migrated component takes `open: boolean` if it didn't already, and the Dialog wraps its body conditionally.
- **`<Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>` vs. always-true open.** If the parent unconditionally renders the modal (some do; some gate with `{open && ...}`), Radix Dialog with `open={true}` and an `onOpenChange` that only calls onClose-on-close is safe — Radix only triggers `onOpenChange(false)` on Escape/click-outside/X.
- **Codex rescue lag.** Codex CLI v0.133.0 has the grammar quirks documented in `active-redesign.md`. Use `codex review --commit <SHA> "<prompt>"` or `cat | codex review --uncommitted` to dodge.
- **Profile delete UX change.** Going from inline-expand to a Dialog could surprise the user. Mitigation: dialog opens immediately on "Delete account" click, same flow, just with proper modal semantics + a destructive `<DialogFooter>` button row.

## Estimated diff

- Tooltip primitive: ~60 LoC.
- Theme-toggle Tooltip wiring + `<TooltipProvider>` in layout: ~15 LoC.
- ai-outline-modal: net -25 / +10 LoC.
- ingest-modal: net -25 / +10 LoC.
- onboarding-tour: net -25 / +10 LoC.
- profile delete: net -20 / +35 LoC (the inline expand was small; the Dialog is more).
- Tooltip tests: ~80 LoC.
- globals.css: +3 LoC.
- Loop docs: ~400 LoC (doesn't count).
- STATUS + CHANGELOG: ~30 LoC.
- pnpm-lock churn: ~30 LoC.

**Total source diff: ~250 LoC** (excluding rescue follow-ups). Well under cap.
