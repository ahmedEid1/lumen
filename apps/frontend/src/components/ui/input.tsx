import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Workbench Input.
 *
 * Inputs sit on muted (surface-2) so the border barely shows at rest;
 * focus tightens the border to the lime ring rather than glowing.
 */

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md px-3 py-2 font-body text-sm",
        "border border-border bg-muted text-foreground",
        "transition-colors duration-base",
        "focus-visible:border-ring focus-visible:bg-background focus-visible:outline-none",
        "placeholder:text-muted-foreground/60",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };
