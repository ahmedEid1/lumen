# ADR-0022: Return focus to the opener for controlled dialogs

- **Status:** Accepted
- **Date:** 2026-05-28
- **Deciders:** @ahmedEid1

## Context

Most of Lumen's dialogs are *controlled* — rendered as
`<Dialog open={...} onOpenChange={...}>` (or the `Sheet` equivalent)
opened by a separate button or hotkey, with no Radix `<DialogTrigger>`.
Radix restores focus on close by focusing the `DialogTrigger`; with no
trigger it has nothing to restore to, so focus falls to `<body>`. A
keyboard or screen-reader user who opens a dialog and closes it loses
their place and must re-traverse from the top of the page — a WCAG
2.4.3 (Focus Order) defect. Found during the iter-11 keyboard pass on
the command palette, then confirmed systemic (AI-outline modal, ingest,
MCP-client mint/reveal, course tutor dialog, profile delete-confirm).

## Decision

A shared hook, `apps/frontend/src/lib/a11y/use-return-focus.ts`:
`useReturnFocus(open: boolean)` captures `document.activeElement` on the
false→true transition (read during render, before Radix's layout-effect
moves focus, so it's the opener) and returns a stable `onCloseAutoFocus`
handler that `preventDefault()`s Radix's default and focuses the
captured opener (guarded by `isConnected` + `typeof focus`). Every
controlled dialog passes it to its `DialogContent`/`SheetContent`
`onCloseAutoFocus`. **New controlled dialogs must use this hook.**

## Alternatives considered

- **Fix at the Dialog primitive** — rejected: controlled dialogs flip
  `open` outside Radix's `onOpenChange`, so the primitive can't capture
  the opener before focus moves. Capture must happen at/below the
  consumer's render.
- **Per-dialog inline capture** (as first shipped for the command
  palette) — works but duplicates the logic; the hook DRYs it.

## Consequences

- **Positive:** keyboard/SR focus is preserved across dialog close
  app-wide; one tested hook covers current + future dialogs.
- **Neutral:** the hook reads `document.activeElement` during render (a
  ref write guarded by a prev-`open` ref) — a deliberate, idempotent
  use of the "capture-on-transition" escape hatch, necessary because a
  `useEffect` would run after Radix already moved focus.

## References

- `apps/frontend/src/lib/a11y/use-return-focus.ts`
- Reference impl: `apps/frontend/src/components/shared/command-palette.tsx`
- WCAG 2.4.3 Focus Order.
