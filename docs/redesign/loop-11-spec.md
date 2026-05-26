# Loop 11 — spec

Selected option: **C** (Popover + DropdownMenu primitives + 3 migrations: notifications-bell, locale-switcher, mobile menu).

## Files touched

### New
- `apps/frontend/src/components/ui/popover.tsx` — Workbench Popover.
- `apps/frontend/src/components/ui/dropdown-menu.tsx` — Workbench DropdownMenu with full sub-component family.
- `apps/frontend/tests/popover.test.tsx` — Popover unit coverage.
- `apps/frontend/tests/dropdown-menu.test.tsx` — DropdownMenu unit coverage.
- `docs/redesign/loop-11-{goal,options,spec,result}.md`.

### Edited
- `apps/frontend/src/components/shared/notifications-bell.tsx` — migrate to `<Popover>`. Net: -45 / +35 LoC.
- `apps/frontend/src/components/shared/locale-switcher.tsx` — migrate from cycle-button to `<DropdownMenu>`. Net: -10 / +35 LoC.
- `apps/frontend/src/components/shared/site-header.tsx` — migrate mobile menu from `border-t` block to `<Sheet>`. Net: -25 / +20 LoC.
- `apps/frontend/src/lib/i18n/messages/en.ts` + `ar.ts` — add `header.mobileNavLabel` if needed; add `localeSwitcher.selectLanguage` label if the existing `common.language` doesn't slot in. Check parity.
- `apps/frontend/tests/notifications-bell.test.tsx` — touch as needed for the Popover-rendered markup (role names, query selectors).
- `apps/frontend/tests/locale-switcher-aria.test.ts` — extend if new keys land.
- `apps/frontend/package.json` + `pnpm-lock.yaml`.
- `docs/redesign/STATUS.md`, `CHANGELOG.md`.

## Popover primitive

- Built on `@radix-ui/react-popover`.
- Default `side="bottom"`, `align="end"`, `sideOffset={6}`.
- Content surface: `bg-card border border-border rounded-md` — no shadow, Workbench rule.
- Z-index from Loop 1 ramp: `z-popover`.
- Animation: same `fade-in` keyframe as Dialog overlay (already in globals.css), keyed off `data-state=open` + `data-wb-popover-content`.

## DropdownMenu primitive

- Built on `@radix-ui/react-dropdown-menu`.
- Same `bg-card border border-border rounded-md` surface as Popover.
- Sub-components:
  - `DropdownMenuTrigger` (= Radix Trigger)
  - `DropdownMenuContent` (= Radix Content, Workbench-styled)
  - `DropdownMenuItem` — text + optional left icon slot
  - `DropdownMenuLabel` — non-interactive header
  - `DropdownMenuSeparator` — `hairline` utility
  - `DropdownMenuCheckboxItem` — Radix CheckboxItem with the Check from lucide
  - `DropdownMenuRadioGroup` + `DropdownMenuRadioItem` — Radix RadioGroup + RadioItem with the Check indicator on the active one
- `data-wb-dropdown-content` for the open animation hook (same `fade-in` rule).

## notifications-bell migration

Before:
```tsx
<div className="relative">
  <Button ... onClick={() => setOpen((v) => !v)} ...>
    <Bell ... />
    {unread > 0 && <span ...badge.../>}
  </Button>
  {open && (
    <>
      <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
      <div className="surface absolute end-0 z-40 mt-2 w-80 overflow-hidden">
        {/* header + list */}
      </div>
    </>
  )}
</div>
```

After:
```tsx
<Popover open={open} onOpenChange={setOpen}>
  <PopoverTrigger asChild>
    <Button ... aria-label={…}>
      <Bell ... />
      {unread > 0 && <span ...badge.../>}
    </Button>
  </PopoverTrigger>
  <PopoverContent align="end" className="w-80 overflow-hidden p-0">
    {/* header + list — moved verbatim from inside the absolute panel */}
  </PopoverContent>
</Popover>
```

The `<div className="relative">` wrapper goes away because Radix Popover handles its own positioning. Click-outside, Escape, focus-restore: all from Radix. The state hook stays — Popover supports controlled `open`/`onOpenChange`.

## locale-switcher migration

Before: cycle button. After: real dropdown with the active locale showing a check.

```tsx
export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`${t("common.language")}: ${LOCALE_LABELS[locale]}`}
        >
          <Languages className="h-5 w-5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[10rem]">
        <DropdownMenuLabel>{t("common.language")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={locale}
          onValueChange={(v) => setLocale(v as (typeof LOCALES)[number])}
        >
          {LOCALES.map((l) => (
            <DropdownMenuRadioItem key={l} value={l}>
              {LOCALE_LABELS[l]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

The aria-label literal (`${t("common.language")}: ${LOCALE_LABELS[locale]}`) is preserved — `tests/locale-switcher-aria.test.ts` keeps passing. The e2e regex in `learner-journey.spec.ts:71` (matches `/language|اللغة/i`) keeps matching.

## mobile menu migration

Before: `border-t` block toggled by `menuOpen` state, sits inside the header element.

After:
```tsx
<Sheet open={menuOpen} onOpenChange={setMenuOpen}>
  <SheetTrigger asChild>
    <Button
      variant="ghost"
      size="icon"
      className="md:hidden"
      aria-label={menuOpen ? t("header.closeMenu") : t("header.openMenu")}
      aria-expanded={menuOpen}
      aria-controls="mobile-nav-sheet"
    >
      {menuOpen ? <X /> : <Menu />}
    </Button>
  </SheetTrigger>
  <SheetContent side="right" className="w-72" id="mobile-nav-sheet">
    <SheetTitle className="sr-only">{t("header.mobileMenu")}</SheetTitle>
    <nav ...>{links + search + auth — moved verbatim}</nav>
  </SheetContent>
</Sheet>
```

The `useEffect(() => setMenuOpen(false), [pathname])` close-on-navigate hook stays — the Sheet is controlled by `menuOpen`.

The `aria-controls="mobile-nav"` ID still points to a div with id `mobile-nav-sheet` (Radix portals the content, so the ID lives on `SheetContent` itself).

## Tests

`apps/frontend/tests/popover.test.tsx` (~120 LoC):
- Trigger opens.
- Escape closes.
- Click outside closes.
- `align="end"` propagates as data attribute.
- Controlled mode (open/onOpenChange) works.

`apps/frontend/tests/dropdown-menu.test.tsx` (~150 LoC):
- Trigger opens, renders all items with `role="menuitem"`.
- Arrow-down moves selection (Radix-handled).
- Escape closes.
- RadioGroup + RadioItem: `aria-checked` on active.
- CheckboxItem: toggles `aria-checked`.
- Separator renders with `role="separator"`.
- Label renders, non-interactive (no `role="menuitem"`).

`apps/frontend/tests/notifications-bell.test.tsx` — confirm tests still pass with the new Popover-rendered markup. May need to adjust `getByRole("button", { name: /notifications/i })` to handle the trigger button vs the inner mark-all-read button. Radix portals the content, so `screen.findByText(...)` still works.

## Risks

- **Sheet anchor positioning vs current viewport assumptions.** The current mobile menu sits below the header (`border-t`). Sheet portals to body, so it floats above. Verify on a real mobile viewport via Playwright — the Sheet should cover the header area, not avoid it. Acceptable: Sheet has its own close X, so users don't need to see the underlying hamburger.
- **`useEffect(setMenuOpen(false), [pathname])` race.** When a nav link closes the menu via state change AND Radix's own focus-restore runs, focus might land oddly. Mitigation: Sheet's `onOpenChange` is the single source of truth; the pathname-effect just sets the state.
- **i18n keys for the language label.** `LOCALE_LABELS` come from `@/lib/i18n/locales`; no new keys needed. If parity test fails, surface and add the missing key on the fly.

## Estimated diff

- Popover primitive: ~80 LoC.
- DropdownMenu primitive: ~180 LoC (more sub-components).
- Migrations: net ~+50 LoC across 3 files.
- Tests: ~270 LoC.
- Loop docs: ~400 LoC (doesn't count).
- STATUS + CHANGELOG: ~15 LoC.
- pnpm-lock churn: ~50 LoC (two new Radix deps).

**Total source diff: ~600 LoC.** Comfortably under the 2000 LoC soft cap.
