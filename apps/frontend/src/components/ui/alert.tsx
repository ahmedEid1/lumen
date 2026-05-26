import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench Alert.
 *
 * Page-level banner — "the email is unverified", "the course is in
 * draft", "we couldn't reach the LLM". For *inline form errors*,
 * reach for `<Field error="…">` instead; conflating the two produces
 * oversized form errors and undersized page banners.
 *
 * Tones map 1:1 to the semantic colour tokens — `info` exercises the
 * loop-1 `--info` blue, the other three exercise the existing
 * success / warning / destructive tokens. Border-elevation only; no
 * shadow, no glow.
 */
const alertVariants = cva(
  "flex items-start gap-3 rounded-md border p-4",
  {
    variants: {
      tone: {
        info: "border-info/40 bg-info/10",
        success: "border-success/40 bg-success/10",
        warning: "border-warning/40 bg-warning/10",
        destructive: "border-destructive/40 bg-destructive/10",
      },
    },
    defaultVariants: { tone: "info" },
  },
);

const iconToneClasses = {
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
} as const;

const titleToneClasses = {
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
} as const;

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  icon?: LucideIcon;
  title?: string;
}

export function Alert({
  tone = "info",
  icon: Icon,
  title,
  className,
  children,
  ...props
}: AlertProps) {
  const t = tone ?? "info";
  // role="alert" interrupts assistive tech; reserve for destructive
  // banners that warrant immediate attention. role="status" is the
  // polite live region for informational / success / warning bands.
  const role = t === "destructive" ? "alert" : "status";
  return (
    <div
      role={role}
      className={cn(alertVariants({ tone: t }), className)}
      {...props}
    >
      {Icon ? (
        <Icon
          aria-hidden="true"
          className={cn("h-4 w-4 flex-shrink-0 mt-0.5", iconToneClasses[t])}
        />
      ) : null}
      <div className="flex-1 space-y-1">
        {title ? (
          <p
            className={cn(
              "font-body text-sm font-semibold leading-tight",
              titleToneClasses[t],
            )}
          >
            {title}
          </p>
        ) : null}
        {children ? (
          <div className="font-body text-sm leading-relaxed text-foreground/90">
            {children}
          </div>
        ) : null}
      </div>
    </div>
  );
}
