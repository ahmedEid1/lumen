import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Workbench Textarea. Same surface treatment as Input — sits on
 * muted, focus tightens to the lime ring.
 */
export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-24 w-full rounded-md px-3 py-2 font-body text-sm",
        "border border-border bg-muted text-foreground",
        "transition-colors duration-[160ms]",
        "focus-visible:border-ring focus-visible:bg-background focus-visible:outline-none",
        "placeholder:text-muted-foreground/60",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export { Textarea };
