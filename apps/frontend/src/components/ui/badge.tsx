import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Workbench Badge.
 *
 * Mechanical pill, not rounded-full. Borders carry the colour rather
 * than fills — a badge is metadata, not a button, so it should never
 * grab as much attention as a CTA. Mono variant pairs with the
 * tabular-numerics font for IDs / counts / durations.
 */
const badgeVariants = cva(
  "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wider transition-colors",
  {
    variants: {
      variant: {
        default: "border-primary/40 bg-primary/10 text-primary",
        secondary: "border-border bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        muted: "border-border bg-muted text-muted-foreground",
        success: "border-success/40 bg-success/10 text-success",
        warning: "border-warning/40 bg-warning/10 text-warning",
        destructive: "border-destructive/40 bg-destructive/10 text-destructive",
        mono: "border-border bg-muted font-mono text-muted-foreground normal-case tracking-normal",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant, className }))} {...props} />;
}
