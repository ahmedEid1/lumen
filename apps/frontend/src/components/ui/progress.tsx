"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";

/**
 * Workbench Progress.
 *
 * Thin (4px) bar, flat ends. The lime indicator advances on a
 * 240ms quart-out ease — slow enough to read, fast enough not to
 * feel laggy. No glow, no shimmer.
 */
export const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn(
      "relative h-1 w-full overflow-hidden rounded-sm bg-muted",
      className,
    )}
    {...props}
  >
    <ProgressPrimitive.Indicator
      className="h-full w-full flex-1 bg-primary"
      style={{
        transform: `translateX(-${100 - (value ?? 0)}%)`,
        transition: "transform 240ms cubic-bezier(0.16, 1, 0.3, 1)",
      }}
    />
  </ProgressPrimitive.Root>
));
Progress.displayName = ProgressPrimitive.Root.displayName;
