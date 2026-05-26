# Loop 10 — options

Three approaches considered for the Dialog + Sheet + tutor-modal migration. AUDIT.md §1 calls for Radix-backed primitives; the choice here is mostly the **migration cadence**, not whether to use Radix.

## Option A — All-in-one foundation pass

Ship all 5 overlay primitives (Dialog, Sheet, Popover, DropdownMenu, Tooltip) AND migrate all 8 hand-rolled overlays in one loop.

- **Pros:** one CHANGELOG entry, one Codex review surface for the entire overlay layer, end-to-end coherence guaranteed.
- **Cons:** trips the 2000-LoC soft cap (estimate ~2400 LoC). 8 migrations × ~50 LoC each = 400 LoC, + 5 primitives × ~80 LoC = 400 LoC, + tests ~600 LoC, + visual-regression rebless on multiple surfaces ~200 LoC of baselines, + studio surfaces touch i18n keys. Single failure in any migration blocks the whole loop.

## Option B — Two-loop split: primitives first, migrations second (NOT chosen)

Loop 10 = all 5 primitives, zero migration. Loop 11 = all 8 migrations.

- **Pros:** primitives loop is small + reviewable. Migration loop is mechanical.
- **Cons:** **primitive loop ships unused code** — no consumer means we can't verify the primitive API survives contact with a real callsite. Easy to over-design or under-design without the discipline of a migration target. Codex rescues hate "primitives with no usage" — too easy to bikeshed the API.

## Option C — Primitive + critical-path migration per loop (CHOSEN)

Loop 10 = Dialog + Sheet primitives + tutor-modal migration (highest a11y blast radius).
Loop 11 = Popover + DropdownMenu + Tooltip + the remaining 7 migrations.

- **Pros:** each loop ships a primitive **plus** a real consumer that exercises its API. Forces the primitive API to be useful from line 1. Stays under 2000 LoC. Tutor modal is the most-visited overlay (every enrolled learner on every course detail), so the a11y fix lands first.
- **Cons:** Sheet ships without a migration target in this loop (its targets are mobile menu + future studio side-panels, both Loop 11). Justification: it's `cva`-variant-different from Dialog only — the API doesn't need a separate consumer to validate it; the Dialog API IS the Sheet API.

## Decision

**Option C.** Primary reasons:
1. Soft cap. 2000 LoC is a real constraint; Option A overshoots.
2. The tutor modal is the most-defended a11y win — no focus trap on the modal a learner uses every session is the worst-state issue. Fixing it in the same loop as the primitive shrinks the time-to-value.
3. Sheet ride-along is cheap because Radix `<Dialog>` underpins both — they're literally the same primitive with different content positioning + animation.

## Concrete API sketch (binding once spec lands)

```tsx
// Dialog
<Dialog open={open} onOpenChange={setOpen}>
  <DialogTrigger asChild><Button>Open</Button></DialogTrigger>
  <DialogContent className="max-w-xl">
    <DialogHeader>
      <DialogTitle>Title</DialogTitle>
      <DialogDescription>Subtitle copy.</DialogDescription>
    </DialogHeader>
    {/* body */}
    <DialogFooter>
      <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
      <Button>Confirm</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>

// Sheet — same as Dialog but slides in from a side
<Sheet open={open} onOpenChange={setOpen}>
  <SheetTrigger asChild><Button>Menu</Button></SheetTrigger>
  <SheetContent side="right" className="w-80">
    <SheetHeader>
      <SheetTitle>Menu</SheetTitle>
    </SheetHeader>
    {/* body */}
  </SheetContent>
</Sheet>
```

Both share Radix's escape/click-outside/focus-trap/focus-restore semantics — no custom handlers.
