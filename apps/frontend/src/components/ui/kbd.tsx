import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Workbench Kbd.
 *
 * Semantic `<kbd>` pill for keyboard-shortcut hints. Renders as a
 * small bordered mono-uppercase chip. Pair adjacent `<Kbd>` elements
 * (no joining `+` symbol) — the visual gap reads as a key
 * combination unambiguously.
 *
 * Used by the Cmd+K palette hint, future per-tool hotkey markers
 * (FSRS 1/2/3/4 in `/dashboard/reviews`, Tiptap editor shortcuts).
 *
 * Lives next to other ★-gravity primitives (Spinner, LinkButton,
 * Tooltip) — small parts that the audit bundled together in the
 * "small parts" loop intent. Loop 18 just unboxes this one.
 */
const Kbd = React.forwardRef<
  HTMLElement,
  React.ComponentPropsWithoutRef<"kbd">
>(({ className, children, ...props }, ref) => (
  <kbd
    ref={ref}
    className={cn(
      "inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-border bg-muted/40 px-1",
      "font-mono text-[10px] uppercase tracking-wider text-muted-foreground",
      className,
    )}
    {...props}
  >
    {children}
  </kbd>
));
Kbd.displayName = "Kbd";

export { Kbd };
