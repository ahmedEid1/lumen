import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench Spinner.
 *
 * Lucide `Loader2` + `animate-spin`. The audit found `Loader2` spun
 * inline at half a dozen call sites with bespoke sizes; this primitive
 * locks the size scale and ensures every spinner ships with an
 * accessible name. `role="status"` exposes the spin to screen readers
 * as a loading affordance.
 */
const SIZE_CLASSES = {
  sm: "h-3.5 w-3.5",
  md: "h-4 w-4",
  lg: "h-5 w-5",
} as const;

export interface SpinnerProps
  extends Omit<React.SVGAttributes<SVGSVGElement>, "aria-label"> {
  size?: keyof typeof SIZE_CLASSES;
  /** Defaults to "Loading"; override to describe what's loading. */
  "aria-label"?: string;
}

export function Spinner({
  size = "md",
  className,
  "aria-label": ariaLabel = "Loading",
  ...props
}: SpinnerProps) {
  return (
    <Loader2
      role="status"
      aria-label={ariaLabel}
      className={cn(SIZE_CLASSES[size], "animate-spin", className)}
      {...props}
    />
  );
}
