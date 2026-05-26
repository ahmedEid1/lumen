"use client";

import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench Checkbox.
 *
 * Radix-backed — `aria-checked` semantics, keyboard space-to-toggle,
 * focus ring. Used in multi-select quiz questions (where multiple
 * answers can be correct) and any other surface that needs a single
 * binary toggle (e.g. admin/courses "featured only", lesson "free
 * preview", profile prefs once Switch lands).
 *
 * Item visual matches the radio-group item shell so a multi-select
 * quiz reads visually identical to a single-select one except for
 * the indicator shape (Check ≠ filled-Circle). Both consume the
 * same Workbench primary token.
 */
const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      "grid h-4 w-4 shrink-0 place-items-center rounded-sm border border-muted-foreground/60 text-primary",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      "data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground",
      "disabled:cursor-not-allowed disabled:opacity-60",
      className,
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
      <Check className="h-3 w-3" strokeWidth={3} />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
));
Checkbox.displayName = CheckboxPrimitive.Root.displayName;

export { Checkbox };
