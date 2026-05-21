"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "relative inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md text-sm font-medium tracking-wide",
    "transition-[transform,box-shadow,background-color,color] duration-200",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
    "active:translate-y-px",
  ].join(" "),
  {
    variants: {
      variant: {
        // Gold primary — leaf gradient + sun highlight + flake shadow.
        default: [
          "text-primary-foreground",
          "bg-[linear-gradient(135deg,hsl(var(--gold-leaf))_0%,hsl(var(--gold-sun))_50%,hsl(var(--gold-leaf))_100%)]",
          "bg-[length:200%_100%] bg-[position:0%_50%]",
          "shadow-[0_1px_0_hsl(var(--gold-sun)/0.7)_inset,0_-1px_0_hsl(0_0%_0%/0.25)_inset,0_8px_24px_-8px_hsl(var(--gold-leaf)/0.55)]",
          "hover:bg-[position:100%_50%] hover:shadow-[0_1px_0_hsl(var(--gold-sun)/0.9)_inset,0_-1px_0_hsl(0_0%_0%/0.3)_inset,0_12px_32px_-8px_hsl(var(--gold-leaf)/0.7)]",
        ].join(" "),
        // Outlined in gold — for secondary CTAs.
        outline:
          "border border-gold/40 bg-transparent text-gold hover:border-gold/70 hover:bg-gold/5",
        ghost: "text-foreground/80 hover:bg-muted hover:text-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border",
        link: "text-gold underline-offset-4 decoration-gold/40 hover:underline hover:decoration-gold",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-12 rounded-md px-7 text-base",
        icon: "h-10 w-10",
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
