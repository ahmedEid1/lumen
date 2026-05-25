"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Workbench Button.
 *
 * Borders do the elevation work. No box-shadows on default state — a
 * subtle background shift on hover (~4% luminance) is enough. Focus is
 * a 2px lime ring with a 2px offset; nothing else moves. Primary CTAs
 * carry the lime, but never more than one per screen — secondary
 * actions are bordered ghosts on the surface-1 background.
 */
const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md text-sm font-medium",
    "transition-colors duration-[160ms]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
  ].join(" "),
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        outline:
          "border border-border bg-transparent text-foreground hover:bg-muted",
        ghost: "text-foreground/80 hover:bg-muted hover:text-foreground",
        // text-white instead of text-destructive-foreground: the latter
        // resolves to the near-white --destructive-foreground token, but
        // pairing it with `bg-destructive` (at the design-token's red
        // hue) only clears 3.24:1 contrast — fails axe-core's WCAG 1.4.3
        // AA gate. Pure white on `bg-destructive` (the darkened 40% L
        // red set in globals.css) clears 4.5:1 with margin. The other
        // `text-destructive` usages (badges, banner text) sit on
        // muted/transparent backgrounds so they pass on their own.
        destructive:
          "bg-destructive text-white hover:bg-destructive/90",
        secondary:
          "border border-border bg-secondary text-secondary-foreground hover:bg-muted",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-5 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
