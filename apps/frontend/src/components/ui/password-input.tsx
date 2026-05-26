"use client";

import * as React from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

/**
 * Workbench PasswordInput.
 *
 * Wraps `<Input>` and stacks an Eye/EyeOff toggle on the trailing
 * edge. Click flips `type` between "password" and "text"; value is
 * preserved across the toggle.
 *
 * Used by /login, /register, /reset-password (Loop 15) and any
 * future surface that asks the user for a password. The toggle's
 * `aria-label` is translated so non-English users hear the right
 * affordance.
 *
 * Why a wrapper instead of an Input variant: the Input primitive
 * stays single-responsibility (a text field). Composition keeps
 * password-specific UI (eye toggle) out of the base component.
 */
const PasswordInput = React.forwardRef<
  HTMLInputElement,
  Omit<React.ComponentPropsWithoutRef<typeof Input>, "type">
>(({ className, ...props }, ref) => {
  const t = useT();
  const [revealed, setRevealed] = React.useState(false);
  return (
    <div className="relative">
      <Input
        ref={ref}
        type={revealed ? "text" : "password"}
        className={cn("pe-10", className)}
        {...props}
      />
      <button
        type="button"
        onClick={() => setRevealed((v) => !v)}
        aria-label={
          revealed ? t("auth.password.hide") : t("auth.password.show")
        }
        aria-pressed={revealed}
        className={cn(
          "absolute end-2 top-1/2 -translate-y-1/2 inline-grid h-7 w-7 place-items-center rounded-md",
          "text-muted-foreground transition-colors duration-base",
          "hover:bg-muted hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        )}
      >
        {revealed ? (
          <EyeOff className="h-4 w-4" aria-hidden />
        ) : (
          <Eye className="h-4 w-4" aria-hidden />
        )}
      </button>
    </div>
  );
});
PasswordInput.displayName = "PasswordInput";

export { PasswordInput };
