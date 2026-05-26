import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Workbench AuthCard.
 *
 * One primitive that owns the seven byte-identical auth chromes the
 * audit named (cross-cutting #1): outer max-w-[440px] wrapper, bordered
 * card on `bg-card`, mono cartouche eyebrow, display heading, optional
 * subtitle. Pages drop their form / status content into `children`.
 *
 * The hydration gate is deliberately NOT owned by this primitive —
 * pages that need it call `useHydrated()` directly. Some auth surfaces
 * (verify-email, confirm-email-change) auto-fire on mount and don't
 * have a submit button to gate, so the hook is a per-page concern.
 * See `docs/redesign/loop-4-options.md` decision 2 for the call.
 */
export interface AuthCardProps {
  cartouche: string;
  heading: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}

export function AuthCard({
  cartouche,
  heading,
  subtitle,
  children,
  className,
}: AuthCardProps) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[440px] flex-col px-6 py-20",
        className,
      )}
    >
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {cartouche}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {heading}
          </h1>
          {subtitle ? (
            <p className="font-body text-sm text-muted-foreground">{subtitle}</p>
          ) : null}
        </header>
        {children}
      </div>
    </div>
  );
}
