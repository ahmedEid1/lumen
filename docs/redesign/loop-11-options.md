# Loop 11 — options

Three approaches considered for the Popover + DropdownMenu + migrations.

## Option A — Primitives only

Ship Popover + DropdownMenu, no migrations. Save migrations for a follow-up loop.

- **Pros:** smallest possible diff (~250 LoC primitive + 250 LoC tests = 500 total). Easy to review.
- **Cons:** Same anti-pattern as Loop 10's option B — primitives without consumers can't be validated. Worse here: notifications-bell + locale-switcher are visible, broken-by-design overlays today (the bell has no Escape, the switcher has no UI), so leaving them unfixed is a missed user-visible win.

## Option B — Primitives + ALL 7 audit-flagged overlay migrations (NOT chosen)

Ship Popover + DropdownMenu + Tooltip + 7 migrations (the remaining 4 Dialog migrations + notif-bell + locale-switcher + mobile menu).

- **Pros:** clears the entire overlay backlog in one push.
- **Cons:** Heavily overshoots the 2000 LoC soft cap (estimate ~2800 LoC). Each ai-outline-modal / ingest-modal migration is ~80-120 LoC because they have complex internal state (multi-step ingest flow). Single-loop blast radius — a Tooltip integration regression would block the 4 Dialog migrations.

## Option C — Primitives + 3 strategic migrations (CHOSEN)

Ship Popover + DropdownMenu + the 3 migrations that each exercise a different new primitive:

- **notifications-bell** validates Popover (most visited overlay outside the tutor modal; visible to every authenticated user).
- **locale-switcher** validates DropdownMenu (replaces the "no dropdown exists yet" cycle behaviour the audit called out specifically).
- **site-header mobile menu** validates Sheet from Loop 10 (Sheet currently has zero consumers).

Tooltip + 4 Dialog migrations → Loop 12.

- **Pros:** each new primitive ships with at least one real consumer. Sheet finally has a consumer too — closes the "primitive shipped without a consumer" risk left over from Loop 10. Stays under the 2000 LoC cap (~1100 LoC estimate).
- **Cons:** ai-outline-modal et al. wait a loop. Acceptable — they all hit ★ admin/studio surfaces, not learner-facing paths.

## Decision

**Option C.** Primary reasons:
1. Sheet has been sitting unused since Loop 10. Mobile menu migration validates it.
2. Each loop should ship a primitive + a real consumer (the rule we established in Loop 10).
3. Tooltip's only natural consumer in the current codebase is the locale-switcher `title=` attr — which DropdownMenu replaces anyway. Tooltip can wait until KBD shortcuts land (Cmd+K loop).

## Concrete API sketches

```tsx
// Popover
<Popover open={open} onOpenChange={setOpen}>
  <PopoverTrigger asChild>
    <Button variant="ghost" size="icon"><Bell /></Button>
  </PopoverTrigger>
  <PopoverContent align="end" className="w-80 p-0">
    {/* body */}
  </PopoverContent>
</Popover>

// DropdownMenu — locale-switcher pattern
<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="ghost" size="icon" aria-label="…"><Languages /></Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent align="end">
    <DropdownMenuLabel>{t("common.language")}</DropdownMenuLabel>
    <DropdownMenuRadioGroup value={locale} onValueChange={(v) => setLocale(v as Locale)}>
      {LOCALES.map((l) => (
        <DropdownMenuRadioItem key={l} value={l}>
          {LOCALE_LABELS[l]}
        </DropdownMenuRadioItem>
      ))}
    </DropdownMenuRadioGroup>
  </DropdownMenuContent>
</DropdownMenu>

// Sheet — mobile menu pattern
<Sheet open={menuOpen} onOpenChange={setMenuOpen}>
  <SheetTrigger asChild>
    <Button variant="ghost" size="icon" className="md:hidden" aria-label={…}>
      <Menu />
    </Button>
  </SheetTrigger>
  <SheetContent side="right" className="w-72">
    <SheetTitle className="sr-only">{t("header.mobileMenu")}</SheetTitle>
    {/* nav links + search + auth */}
  </SheetContent>
</Sheet>
```
