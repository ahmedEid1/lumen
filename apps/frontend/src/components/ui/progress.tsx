"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";

/**
 * Progress — gold-leaf gradient indicator on a recessed muted track.
 * The thin inset border + soft track read as a carved channel; the
 * indicator reads as molten gold filling it. Subtle gold glow at the
 * leading edge keeps the bar visible against lapis-dark backgrounds.
 */
export const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-muted",
      "shadow-[inset_0_1px_0_hsl(0_0%_0%/0.25)]",
      className,
    )}
    {...props}
  >
    <ProgressPrimitive.Indicator
      className={cn(
        "h-full w-full flex-1 transition-transform duration-500",
        "bg-[linear-gradient(90deg,hsl(var(--gold-leaf))_0%,hsl(var(--gold-sun))_55%,hsl(var(--gold-leaf))_100%)]",
        "shadow-[0_0_12px_hsl(var(--gold-leaf)/0.45)]",
      )}
      style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }}
    />
  </ProgressPrimitive.Root>
));
Progress.displayName = ProgressPrimitive.Root.displayName;
