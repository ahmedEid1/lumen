# Loop 11 — goal

Foundation C, slice 2: **Popover + DropdownMenu primitives + 3 overlay migrations**.

## Why now

Loop 10 shipped Dialog + Sheet + the tutor-modal migration. The remaining overlay primitives from AUDIT.md §2 are Popover, DropdownMenu, and Tooltip. This loop covers the first two plus three migrations that exercise the new primitives + Sheet (which has no consumer yet in Loop 10).

Tooltip is deferred to Loop 12 because: (a) it's low gravity (★) per the audit — only 2-3 surfaces would use it; (b) the 3-primitive-2-migration ceiling is already at the soft cap.

## What "done" looks like

1. **`apps/frontend/src/components/ui/popover.tsx`** — Radix Popover with `Popover`, `PopoverTrigger`, `PopoverContent`. Workbench-styled surface. Anchored to trigger with side/align props (default `side="bottom"`, `align="end"` to match notifications-bell positioning).
2. **`apps/frontend/src/components/ui/dropdown-menu.tsx`** — Radix DropdownMenu with `DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuLabel`, `DropdownMenuSeparator`, `DropdownMenuCheckboxItem`, `DropdownMenuRadioGroup`, `DropdownMenuRadioItem`. Same surface chrome as Popover.
3. **`notifications-bell.tsx` → Popover.** Replace lines 91-149 (hand-rolled `fixed inset-0 z-30` overlay + `absolute end-0 z-40` panel) with `<Popover>` + `<PopoverContent>`. Closes ESC, click-outside, focus-restore. Preserves: unread badge, mark-all-read button, navigation on item click.
4. **`locale-switcher.tsx` → DropdownMenu.** Today it cycles through locales because "adding a Radix dropdown for two options is silly" (per the source comment). With DropdownMenu now in the kit, the cost-of-real-dropdown drops to ~10 LoC; flip it to a `DropdownMenuRadioGroup` of locales. Future-proofs for adding a 3rd locale and removes the source-of-truth jab.
5. **`site-header.tsx` mobile menu → Sheet.** Today is a hand-rolled `border-t` slide-down. Migrate to `<Sheet side="right">` for swipe-from-edge feel, focus trap, and the audit's flagged "no slide-in animation, no swipe-close, no portal" issues.
6. **Unit tests** in `apps/frontend/tests/popover.test.tsx` + `dropdown-menu.test.tsx` (~150 LoC each).
7. **Existing notifications-bell + locale-switcher tests stay green** — the migration aims for behaviour-preservation; tests may need light tweaks (e.g. role names) but no logic changes.
8. **`make test.web` green** end-to-end (38+ files, 230+ tests).
9. **STATUS.md row + CHANGELOG entry + `loop-11-result.md`** retrospective.

## Out of scope

- Tooltip primitive → Loop 12.
- ai-outline-modal, ingest-modal, onboarding-tour, profile delete-confirm migrations to Dialog → Loop 12 (4 modal migrations, each ~30 LoC, batches cleanly).
- Tutor streaming SSE.
- Internal a11y of the tutor (aria-live, focus management on open).
- Locale-switcher RTL flip detail — DropdownMenu's `dir` prop covers it automatically.

## Success criteria (binary)

- [ ] Popover primitive ships, anchored to trigger via Radix.
- [ ] DropdownMenu primitive ships with Item / Label / Separator / CheckboxItem / RadioGroup / RadioItem sub-components.
- [ ] Notifications-bell closes on ESC + clicks restore focus to the bell button.
- [ ] Locale-switcher opens a menu with both locales and a checkmark next to the active one.
- [ ] Mobile menu slides in from the end of the screen + closes on ESC.
- [ ] `make test.web`: green, tests file count grows by 2.
- [ ] CI 5 gates green.
- [ ] Prod deploy + visual review pass.
