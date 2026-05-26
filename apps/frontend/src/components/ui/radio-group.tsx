"use client";

import * as React from "react";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench RadioGroup.
 *
 * Radix-backed — keyboard arrow-key navigation across items, single-
 * selection enforcement, `aria-checked` on each item, fieldset/legend
 * semantics when wrapped accordingly. Replaces the bare `<button>`
 * rows in `lesson-player.tsx:239-256` that the audit flagged as the
 * heaviest a11y violation in the codebase (AUDIT.md §3 Block-renderer).
 *
 * Item visual matches the previous quiz-option button: bordered row,
 * hover shifts the border, selected state lights the border + a soft
 * primary-tinted bg. Inside the item we render a 16px Circle that
 * fills on selection — same pattern as Radix's reference, in the
 * Workbench palette.
 */
const RadioGroup = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>
>(({ className, ...props }, ref) => (
  <RadioGroupPrimitive.Root
    ref={ref}
    className={cn("flex flex-col gap-2", className)}
    {...props}
  />
));
RadioGroup.displayName = RadioGroupPrimitive.Root.displayName;

const RadioGroupItem = React.forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item> & {
    label: React.ReactNode;
  }
>(({ className, label, ...props }, ref) => {
  return (
    <label
      className={cn(
        "group flex w-full cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2 text-start font-body text-sm transition-colors duration-base",
        "hover:border-foreground/30",
        "has-[[data-state=checked]]:border-foreground/40 has-[[data-state=checked]]:bg-muted",
        "has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:opacity-60",
        className,
      )}
    >
      <RadioGroupPrimitive.Item
        ref={ref}
        className={cn(
          "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border border-muted-foreground/60 text-primary",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "data-[state=checked]:border-primary",
        )}
        {...props}
      >
        <RadioGroupPrimitive.Indicator className="flex items-center justify-center">
          <Circle className="h-2 w-2 fill-current text-current" />
        </RadioGroupPrimitive.Indicator>
      </RadioGroupPrimitive.Item>
      <span className="flex-1">{label}</span>
    </label>
  );
});
RadioGroupItem.displayName = RadioGroupPrimitive.Item.displayName;

export { RadioGroup, RadioGroupItem };
