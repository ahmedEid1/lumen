# Loop 12 — goal

Foundation C, slice 3 (final): **Tooltip primitive + 4 modal migrations + Codex rescue #3**.

Closes out the overlay-primitive backlog from AUDIT.md §2 and the modal-migration backlog from AUDIT.md §3. Once this loop lands, every hand-rolled `fixed inset-0` overlay in the app has been replaced with a Radix-backed primitive.

## Why now

- Loops 10-11 shipped Dialog + Sheet + Popover + DropdownMenu. Tooltip is the last overlay primitive on the audit list.
- 4 hand-rolled modals remain: ai-outline-modal (studio), ingest-modal (studio), onboarding-tour, profile delete-confirm.
- Every-3rd-loop Codex rescue cadence anchors on Loop 12 — Loops 10/11/12 form the Foundation C "tier" per AUDIT.md §7.

## What "done" looks like

1. **`apps/frontend/src/components/ui/tooltip.tsx`** — Radix Tooltip with `TooltipProvider`, `Tooltip`, `TooltipTrigger`, `TooltipContent`. Defaults: 300ms delay, no skip-delay-after-close. Workbench surface chrome: small bg-card border-border with mono caps `text-xs`.
2. **Theme toggle in site-header gets Tooltip** as the first consumer (the icon button has `aria-label` only; sighted users with no screen reader get no visible hint of what it does — Tooltip closes that gap).
3. **`ai-outline-modal.tsx` → Dialog**. Replace the `fixed inset-0 z-50` modal chrome + manual Escape useEffect (lines 62-71, 119-145) with `<Dialog>` + `<DialogContent className="max-w-3xl">`. Preserve the 3-phase state machine (brief / review / creating) and the ModuleRow/LessonRow internals verbatim.
4. **`ingest-modal.tsx` → Dialog**. Same pattern. The multi-step ingest flow (YouTube/PDF/text → preview → create) stays put.
5. **`onboarding-tour.tsx` → Dialog**. Smallest of the four; the existing markup already uses `role="dialog"` + `aria-modal="true"` so the migration is mostly chrome-swap.
6. **Profile delete-confirm → Dialog**. Audit specifically flagged: "Delete-confirm is inline expand, no Dialog primitive for an irreversible action." Convert the inline-expand into a confirmation Dialog with the password input + destructive button + cancel.
7. **Tooltip unit tests** in `apps/frontend/tests/tooltip.test.tsx`.
8. **Existing tests stay green** — ai-outline-modal.test.tsx, onboarding-tour.test.tsx, ingest-modal probes inside the studio tests.
9. **Codex rescue #3** at the end. Pass the Loops 10-12 diff to Codex for an independent review. Address any legitimate findings inside this loop's commit (or a follow-up if they need a separate branch of work).
10. **STATUS.md row + CHANGELOG entry + `loop-12-result.md` + `codex-review-loops-10-to-12.md`**.

## Out of scope

- Migration of studio-side dnd-kit DragOverlay / window.prompt() link+image pickers → Loop 13 (studio polish).
- Profile delete: changing the confirmation copy or the password-required flow.
- Tooltip on more than one consumer (theme toggle). Other surfaces that want it (KBD shortcuts, reasoning-panel tool cells) come along when their loops land.
- Sonner pin-off retry (deferred since Loop 7).

## Success criteria (binary)

- [ ] Tooltip primitive ships, anchored via Radix.
- [ ] Theme toggle shows a tooltip on hover.
- [ ] All 4 modal migrations preserve their existing tests + behaviour.
- [ ] Profile delete-confirm renders as a proper Dialog with destructive + cancel buttons.
- [ ] `make test.web`: green, file count grows by 1 (tooltip.test.tsx).
- [ ] CI 5 gates green.
- [ ] Prod deploy + visual review pass.
- [ ] Codex rescue #3 digest written; any legit issues addressed or tracked.
