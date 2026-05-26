# Loop 12 — result

Surface: Foundation C slice 3 (final) — `<Tooltip>` primitive + 4 modal migrations to `<Dialog>` + Codex rescue #3.

**Foundation C closes here.** Every overlay surface AUDIT.md §2 flagged now sits on a Radix primitive.

## What shipped

- **`apps/frontend/src/components/ui/tooltip.tsx`** (47 LoC). Radix Tooltip with `TooltipProvider`, `Tooltip`, `TooltipTrigger`, `TooltipContent`. Mono-caps text on a card surface; `z-tooltip` (60) per the Loop 1 ramp; no arrow (Workbench: simple shapes only); no shadow.
- **`apps/frontend/src/app/layout.tsx`** — wraps the AuthProvider tree in `<TooltipProvider delayDuration={300} skipDelayDuration={150}>` so every Tooltip consumer in the app shares one provider.
- **`apps/frontend/src/components/shared/site-header.tsx`** — theme toggle wrapped in `<Tooltip>` showing `t("header.themeToggle")`. First consumer of the new primitive.
- **`apps/frontend/src/components/studio/ai-outline-modal.tsx`** — migrated to `<Dialog>`. Removed the manual `useEffect` Escape listener + the hand-rolled `fixed inset-0 z-50` chrome + the manual cancel button. Internals (3-phase state machine, ModuleRow/LessonRow, AI flow) preserved verbatim.
- **`apps/frontend/src/components/studio/ingest-modal.tsx`** — same pattern. Removed `useId` (no longer needed — Radix wires `aria-labelledby` itself), the bespoke Escape listener, the absolute-positioned close X, the X import.
- **`apps/frontend/src/components/onboarding/onboarding-tour.tsx`** — migrated to `<Dialog hideCloseButton>` (the tour has its own "Skip" affordance, so we suppress the built-in X). ArrowRight-to-advance listener kept (the only reason the `useEffect` survives). Escape-to-skip now routed through Dialog's `onOpenChange`.
- **`apps/frontend/src/app/profile/page.tsx`** — destructive delete-account flow extracted from inline-expand to a proper Dialog with the password input + destructive `<DialogFooter>` row + cancel. Closes AUDIT.md §3 Profile finding: "Delete-confirm is inline expand, no Dialog primitive for an irreversible action."
- **`apps/frontend/src/styles/globals.css`** — added `[data-state="delayed-open"][data-wb-tooltip-content]` to the existing `fade-in` rule family. One new selector, zero new keyframes.
- **`apps/frontend/tests/tooltip.test.tsx`** (4 tests). Focus-based assertions; pointer-event hover is real-browser-only.
- **`apps/frontend/package.json`** — `@radix-ui/react-tooltip ^1.2.8` added.

## Success criteria

- [x] Tooltip primitive ships, anchored via Radix.
- [x] Theme toggle shows a tooltip on hover/focus.
- [x] All 4 modal migrations preserve their existing tests + behaviour (verified by `make test.web` green on the prior modal suites + the studio + profile flows).
- [x] Profile delete-confirm renders as a proper Dialog with destructive + cancel buttons.
- [x] `make test.web`: 41 files / 232 tests green (+1 file / +4 tests vs Loop 11).
- [ ] CI 5 gates green — pending push.
- [ ] Prod deploy + visual review pass — pending.
- [ ] Codex rescue #3 digest written — to be added after rescue runs.

## Foundation C — done as a tier

Loops 10-12 ship the full overlay primitive family + every overlay migration the audit flagged:

| Primitive | Loop | Consumers landed |
|---|---|---|
| Dialog | 10 | tutor modal (Loop 10); ai-outline, ingest, onboarding, profile-delete (Loop 12) |
| Sheet | 10 | mobile menu (Loop 11) |
| Popover | 11 | notifications-bell |
| DropdownMenu | 11 | locale-switcher |
| Tooltip | 12 | theme-toggle |

Every `fixed inset-0` overlay in `app/` and `components/` is now Radix-backed.

## Lessons

- **`hideCloseButton` was the right escape hatch.** Onboarding-tour ships its own "Skip" affordance + a primary Next/Done CTA. Adding Radix's built-in close X next to those would have read as a third affordance — the prop lets the migration preserve the existing visual contract.
- **`useId` + `aria-labelledby` is redundant when DialogTitle is present.** Radix wires it automatically. The ingest-modal migration deleted a `useId` import + the manual id wiring.
- **Tooltip's sr-only twin trips happy-dom assertions.** Radix renders both a visible card AND an sr-only span with `role="tooltip"` carrying the same text. `getByText` finds 2 matches. The fix is to assert via `findByRole("tooltip")` and `toHaveTextContent(...)`. Pattern worth remembering for future Tooltip tests.
- **Foundation C is done.** This is the first "tier" closed since Loop 1 (which was its own one-loop tier). The audit's overlay backlog is empty.

## Estimated vs actual diff

| Surface | Estimate (spec) | Actual |
|---|---|---|
| Tooltip primitive | ~60 LoC | 47 LoC |
| layout.tsx + theme-toggle Tooltip wiring | ~15 LoC | ~14 LoC |
| ai-outline-modal | net -15 LoC | net -32 LoC |
| ingest-modal | net -15 LoC | net -25 LoC |
| onboarding-tour | net -15 LoC | net -12 LoC |
| profile delete | net +15 LoC | net +25 LoC |
| Tooltip tests | ~80 LoC | 67 LoC |
| globals.css | +3 LoC | +1 LoC |
| Loop docs (g+o+s+r) | ~400 LoC | ~470 LoC |
| STATUS + CHANGELOG | ~30 LoC | ~35 LoC |
| pnpm-lock churn | ~30 LoC | ~25 LoC |

**Total source diff: ~200 LoC** (the modal migrations net negative — Radix replaces a lot of hand-rolled scaffolding). Well under the 2000 LoC soft cap.

## Codex rescue #3

Dispatched after the prod deploy lands. Digest written to `docs/redesign/codex-review-loops-10-to-12.md`. Any legitimate findings either land in this loop's follow-up commit or get tracked as a Loop 13+ scope addition.

(Codex rescue digest pending — added after the rescue runs.)
