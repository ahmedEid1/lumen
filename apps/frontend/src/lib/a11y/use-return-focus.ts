import { useCallback, useRef, type RefObject } from "react";

/**
 * Restore focus to the element that opened a *controlled* Radix dialog
 * when it closes (WCAG 2.4.3 — Focus Order).
 *
 * The gap: Radix restores focus to its `<DialogTrigger>` on close. But
 * our controlled dialogs render `<Dialog open={...} onOpenChange={...}>`
 * with NO trigger — Radix has nothing to restore to, so focus falls to
 * `<body>`, stranding keyboard and screen-reader users. The reference
 * fix lives in `components/shared/command-palette.tsx`; this hook
 * generalises it.
 *
 * Usage:
 *   const onCloseAutoFocus = useReturnFocus(open);
 *   <DialogContent onCloseAutoFocus={onCloseAutoFocus} ... />
 *
 * For conditionally-mounted dialogs (mounted only while open, so the
 * Radix `open` prop is effectively always `true`), call
 * `useReturnFocus(true)` — the first render sees `open=true` with
 * `prevOpen=false`, which is the false→true transition, so the opener
 * is captured correctly.
 *
 * How it captures: we read `document.activeElement` during render on
 * the false→true transition (guarded by a prev-ref). Render runs
 * BEFORE Radix's layout effect moves focus into the dialog, so the
 * active element is still the opener — exactly the node we want to
 * return focus to. The returned callback is stable across renders.
 *
 * `fallbackRef`: when a dialog opens *as another dialog closes* in the
 * same render (e.g. mint → reveal-secret), the captured opener lives
 * inside the closing dialog and is detached by the time this one
 * closes. Pass a ref to a stable element (the flow's real trigger) and
 * it's used when the captured opener is gone.
 */
export function useReturnFocus(
  open: boolean,
  fallbackRef?: RefObject<HTMLElement | null>,
): (e: Event) => void {
  const prevOpen = useRef(false);
  const openerRef = useRef<HTMLElement | null>(null);

  // Capture during render on the false→true transition. This runs
  // before Radix's layout-effect focus move, so activeElement is the
  // opener, not anything inside the dialog.
  if (open && !prevOpen.current) {
    openerRef.current =
      typeof document !== "undefined"
        ? (document.activeElement as HTMLElement | null)
        : null;
  }
  prevOpen.current = open;

  return useCallback(
    (e: Event) => {
      let el = openerRef.current;
      // The captured opener can be detached if it lived inside a dialog
      // that closed as this one opened — fall back to the stable trigger.
      if (!el || !el.isConnected) el = fallbackRef?.current ?? null;
      if (el && el.isConnected && typeof el.focus === "function") {
        // Stop Radix's default restore (which would target a missing
        // trigger and leave focus on <body>) and return it to the opener.
        e.preventDefault();
        el.focus();
      }
    },
    [fallbackRef],
  );
}
