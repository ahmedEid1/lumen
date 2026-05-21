import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        // Base shape
        "flex h-10 w-full rounded-md px-3 py-2 font-body text-sm",
        // Gold-edge default — overridable. The thin gold/25 border +
        // soft background/60 tint reads as inscribed-line-on-papyrus
        // rather than the default soft-grey input.
        "border border-gold/25 bg-background/60",
        // Focus: gold ring + border darken
        "focus-visible:border-gold/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/40",
        // Placeholder: dimmer than foreground so empty inputs read as expectant rather than weighty
        "placeholder:text-muted-foreground/70 placeholder:italic",
        // Disabled
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
