"use client";

import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

/**
 * Workbench Switch.
 *
 * Radix-backed — `role="switch"`, `aria-checked`, keyboard space-
 * to-toggle. Used for boolean preferences where the on/off state
 * matters more than the label phrasing (e.g. lesson "free preview",
 * admin "featured only", admin "active user").
 *
 * Visual:
 *   off — `h-5 w-9 rounded-full border border-border bg-muted`
 *   on  — `bg-primary`
 * The thumb is a 16px circle sliding from start→end on toggle.
 * Logical-property translate (`translate-x-*` with `start/end`
 * semantics) so RTL flips naturally.
 *
 * Pair with a `<label htmlFor>` for accessible-name. The Switch
 * itself doesn't render text — same separation as Checkbox/
 * RadioGroup.
 */
const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent",
      "transition-colors duration-base",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      "disabled:cursor-not-allowed disabled:opacity-50",
      "data-[state=unchecked]:bg-muted data-[state=checked]:bg-primary",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        "pointer-events-none block h-4 w-4 rounded-full bg-background shadow-none ring-0",
        "transition-transform duration-base",
        "data-[state=unchecked]:translate-x-0 data-[state=checked]:translate-x-4",
        "rtl:data-[state=checked]:-translate-x-4",
      )}
    />
  </SwitchPrimitive.Root>
));
Switch.displayName = SwitchPrimitive.Root.displayName;

export { Switch };
