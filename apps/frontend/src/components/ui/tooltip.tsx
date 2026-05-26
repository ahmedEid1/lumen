"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

/**
 * Workbench Tooltip.
 *
 * Radix-backed — keyboard focus + hover triggers, Escape closes,
 * positioning via Floating UI. Used in the site header (theme toggle,
 * Loop 12) and any other surface that has icon-only triggers with
 * only `aria-label`. Sighted users without a screen reader see no
 * visible hint without a tooltip; this primitive closes that gap.
 *
 * Visual: small mono-caps text on a card surface — same energy as
 * `<Badge variant="muted">`. No arrow (Workbench: simple geometric
 * shapes only). No shadow.
 *
 * `TooltipProvider` should wrap the app (in `layout.tsx`) so
 * `delayDuration` + `skipDelayDuration` apply globally.
 */
const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      data-wb-tooltip-content=""
      className={cn(
        "z-tooltip rounded-md border border-border bg-card text-card-foreground",
        "px-2 py-1 font-mono text-[10px] uppercase tracking-wider",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
