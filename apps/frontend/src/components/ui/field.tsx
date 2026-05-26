import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Workbench Field — label + hint + error wrapper around a single
 * input / textarea / select / custom widget. Replaces the
 * `<div className="space-y-1.5"><label …>…</label><Input …/></div>`
 * pattern that the audit found repeated dozens of times across
 * studio, lesson-editor, profile, and auth surfaces.
 *
 * The Field also owns the form-error ARIA wiring. When `error` is
 * set, the child input is cloned with `aria-invalid="true"` and
 * `aria-describedby={errorId}`; when only `hint` is set, the child
 * gets `aria-describedby={hintId}`. Callers stop forgetting either.
 *
 * Required mark renders as `*` after the label text in
 * `text-destructive` — a long-form `(required)` is too noisy for
 * Workbench density.
 */
export interface FieldProps {
  label: string;
  /** Required: must match the child input's `id` so the label clicks through. */
  htmlFor: string;
  hint?: string;
  error?: string;
  required?: boolean;
  className?: string;
  children: React.ReactElement;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: FieldProps) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  const describedBy = errorId ?? hintId;

  // Splice ARIA onto the child input. If the child already sets one of
  // these, the explicit prop wins (Object.assign order — child spread
  // last would dominate, so we put cloneElement's overrides first and
  // child's own props second by reading the child's existing props).
  const childProps = (children.props ?? {}) as Record<string, unknown>;
  const ariaDescribedBy = [childProps["aria-describedby"], describedBy]
    .filter(Boolean)
    .join(" ") || undefined;
  const enhanced = React.cloneElement(children, {
    id: childProps.id ?? htmlFor,
    "aria-invalid": error ? true : childProps["aria-invalid"],
    "aria-describedby": ariaDescribedBy,
  } as Record<string, unknown>);

  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="font-body text-sm font-medium leading-tight"
      >
        {label}
        {required ? (
          <span aria-hidden="true" className="ms-0.5 text-destructive">
            *
          </span>
        ) : null}
      </label>
      {enhanced}
      {error ? (
        <p
          id={errorId}
          role="alert"
          className="font-body text-xs leading-tight text-destructive"
        >
          {error}
        </p>
      ) : hint ? (
        <p
          id={hintId}
          className="font-body text-xs leading-tight text-muted-foreground"
        >
          {hint}
        </p>
      ) : null}
    </div>
  );
}
