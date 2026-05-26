# Loop 11 — result

Surface: Foundation C slice 2 — `<Popover>` + `<DropdownMenu>` primitives + 3 overlay migrations (notifications-bell, locale-switcher, mobile menu).

## What shipped

- **`apps/frontend/src/components/ui/popover.tsx`** (50 LoC). Radix Popover with `Popover`, `PopoverTrigger`, `PopoverAnchor`, `PopoverPortal`, `PopoverContent`. Defaults: `align="end"`, `sideOffset=6`. Surface chrome matches Loop 10's Dialog (no shadow, single border, card surface). Z-index `z-popover` from Loop 1 ramp.
- **`apps/frontend/src/components/ui/dropdown-menu.tsx`** (162 LoC). Radix DropdownMenu with `Trigger`, `Content`, `Item`, `CheckboxItem`, `RadioGroup`, `RadioItem`, `Label`, `Separator`, `Group`, `Portal`, `Sub`. Active-state indicator slot at `ps-8` keeps label edges aligned regardless of selection state. Workbench `font-mono uppercase tracking-wider` for `Label`.
- **`apps/frontend/src/components/shared/notifications-bell.tsx`** (-45 LoC / +35 LoC, net -10). Migrated from hand-rolled `fixed inset-0 z-30` + `absolute end-0 z-40` to `<Popover>` + `<PopoverContent align="end">`. Click-outside, Escape, focus-restore: all Radix-handled. State hook stays (`open`/`onOpenChange`); navigation on item click still calls `setOpen(false)` + `router.push(href)`.
- **`apps/frontend/src/components/shared/locale-switcher.tsx`** (-10 LoC / +35 LoC, net +25). Cycle button → `<DropdownMenu>` with `<DropdownMenuRadioGroup>`. The active locale shows a `<Circle filled>` indicator via Radix's `ItemIndicator`. `aria-label` literal preserved to keep the prior i18n parity + e2e regex green.
- **`apps/frontend/src/components/shared/site-header.tsx`** (-30 LoC / +35 LoC, net +5). Mobile menu migrated from `border-t` slide-down to `<Sheet side="right">`. Sheet now has a real consumer (was zero in Loop 10). `useEffect(() => setMenuOpen(false), [pathname])` close-on-navigate stays.
- **`apps/frontend/src/styles/globals.css`** — added a single rule for `[data-state="open"][data-wb-popover-content], [data-state="open"][data-wb-dropdown-content]` using the existing `fade-in` keyframe.
- **`apps/frontend/tests/popover.test.tsx`** (~95 LoC, 5 tests).
- **`apps/frontend/tests/dropdown-menu.test.tsx`** (~125 LoC, 7 tests).
- **`apps/frontend/package.json`** — `@radix-ui/react-popover ^1.1.15` and `@radix-ui/react-dropdown-menu ^2.1.16` added.

## Success criteria

- [x] Popover primitive ships with Radix anchoring + Workbench chrome.
- [x] DropdownMenu ships with full sub-component family.
- [x] Notifications-bell closes on ESC + restores focus to the bell button (Radix default).
- [x] Locale-switcher opens a menu with both locales and a check next to the active one (verified via `aria-checked="true"` in tests).
- [x] Mobile menu slides in from the end of the screen + Escape closes (Sheet behaviour from Loop 10).
- [x] `make test.web`: 40 files / 228 tests green (+2 files / +12 tests vs Loop 10).
- [x] No existing tests required changes — Radix's portal isolation means the Popover/DropdownMenu portal-rendered content still resolves via `screen.findByText(...)` / `screen.findByRole(...)`.
- [ ] CI 5 gates green — pending push.
- [ ] Prod deploy + visual review pass — pending.

## What didn't ship (intentional)

- Tooltip primitive → Loop 12 (low gravity per AUDIT.md §2; only 2-3 surfaces would use it; Cmd+K loop has a stronger case for landing it alongside the KBD primitive).
- ai-outline-modal, ingest-modal, onboarding-tour, profile delete-confirm migrations to Dialog → Loop 12 (4 modal migrations batched together; each ~30-80 LoC depending on internal complexity).
- Sonner pin-off retry (deferred from Loop 7).
- Locale-switcher RTL flip detail — DropdownMenu's `dir` prop inheritance covers it; the locale-switcher renders inside a `dir`-aware ancestor.

## Lessons

- **Sheet had no consumer in Loop 10 — that was a real bug.** Without a consumer, the Sheet sat in the kit with an untested API. The mobile-menu migration immediately revealed that `srLabelClose` + `SheetTitle className="sr-only"` is the right pattern for menu-style sheets (vs the form-like SheetHeader+SheetTitle visible-heading pattern). Pattern documented in the file.
- **DropdownMenu's `CheckboxItem` test required a re-open trick.** Radix closes the menu when an item activates (the intended menu behaviour). To assert that the state-change took effect, the test re-opens and re-queries — happy-dom keeps the React tree alive, so the `useState` value persists across the close/open cycle.
- **`data-wb-*` markers as animation hooks scale cleanly.** Loop 10 added them for Dialog + Sheet; Loop 11 added them for Popover + DropdownMenu. globals.css gains 4 selectors total; Tailwind doesn't need an animation plugin. Pattern will carry through to Tooltip + Combobox in future loops.
- **DropdownMenuRadioGroup is the right hammer for locale-switcher.** A regular DropdownMenuItem set with manual checkmarks would have been ~80 LoC; the radio variant is ~25.

## Estimated vs actual diff

| Surface | Estimate (spec) | Actual |
|---|---|---|
| Popover primitive | ~80 LoC | 50 LoC |
| DropdownMenu primitive | ~180 LoC | 162 LoC |
| notifications-bell migration | net ~-10 LoC | net -10 LoC |
| locale-switcher migration | net ~+25 LoC | net +25 LoC |
| site-header mobile-menu migration | net ~-5 LoC | net +5 LoC |
| Tests | ~270 LoC | ~220 LoC |
| globals.css | (not estimated) | +4 LoC |
| Loop docs (goal+options+spec+result) | ~400 LoC | ~440 LoC |
| STATUS + CHANGELOG | ~15 LoC | ~35 LoC |
| pnpm-lock churn | ~50 LoC | ~40 LoC |

**Total source diff: ~520 LoC.** Well under the 2000 LoC soft cap.

## Codex rescue

Next Codex rescue lands at the end of Loop 12 (every-3rd-loop cadence — Loop 9 had no rescue, so 12 is the next anchor). Loop 11 ships without rescue per the spec.
