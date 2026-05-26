"use client";

import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

/**
 * Workbench Popover.
 *
 * Radix-backed — Escape closes, click-outside closes, focus trap
 * inside, focus restore to trigger on close, anchored to the
 * trigger via Radix Portal + Floating UI under the hood.
 *
 * Used by notifications-bell (Loop 11) and the future header-search
 * results panel (Cmd+K loop). Same surface chrome as DropdownMenu —
 * no shadow, single border, surface-card background.
 *
 * Defaults match the most-common placement in the app:
 *   side="bottom" + align="end" + sideOffset=6
 * which positions the popover below and right-edge-aligned with
 * its trigger — the notifications-bell pattern.
 */

const Popover = PopoverPrimitive.Root;
const PopoverTrigger = PopoverPrimitive.Trigger;
const PopoverAnchor = PopoverPrimitive.Anchor;
const PopoverPortal = PopoverPrimitive.Portal;

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "end", sideOffset = 6, ...props }, ref) => (
  <PopoverPortal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      data-wb-popover-content=""
      className={cn(
        "z-popover w-72 rounded-md border border-border bg-card text-card-foreground",
        "p-4 outline-none",
        className,
      )}
      {...props}
    />
  </PopoverPortal>
));
PopoverContent.displayName = PopoverPrimitive.Content.displayName;

export { Popover, PopoverTrigger, PopoverAnchor, PopoverPortal, PopoverContent };
