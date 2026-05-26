import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench EmptyState.
 *
 * Centred column inside a bordered `surface` block (consumes the
 * existing utility from globals.css). Replaces the ~one-off per
 * surface `<div className="surface p-8">…</div>` shapes catalogued in
 * AUDIT.md §2 ("Every surface rolls a one-off …"). Icon, title,
 * optional body, optional CTA.
 *
 * Pass `icon` as the lucide component (not an element): `<EmptyState
 * icon={Search} … />`. The primitive renders the icon at the
 * decoration opacity from the loop-1 token ramp.
 */
export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  body?: string;
  cta?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  cta,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "surface flex flex-col items-center justify-center gap-3 p-8 text-center",
        className,
      )}
    >
      {Icon ? (
        <Icon
          aria-hidden="true"
          className="h-10 w-10 text-muted-foreground/40"
        />
      ) : null}
      <p className="font-display text-lg tracking-tight">{title}</p>
      {body ? (
        <p className="font-body text-sm text-muted-foreground">{body}</p>
      ) : null}
      {cta ? <div className="mt-2">{cta}</div> : null}
    </div>
  );
}
