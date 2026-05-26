import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Workbench Skeleton.
 *
 * Shape-based variants so consumers spell intent (`variant="image"`)
 * rather than pixel sizes. The `text` variant is a flex column of
 * three lines at decreasing widths — the canonical prose-block
 * skeleton; consumers stop hand-rolling `<div className="space-y-2">`
 * + three `<div className="h-4 …" />`s.
 *
 * Width defaults to `w-full`; wrap the Skeleton in the layout's width
 * if you need it narrower. Don't override the variant-fixed *height*
 * — variants encode the slot shape, not just a token.
 *
 * Replaces the five different loading conventions catalogued in
 * AUDIT.md §4 #4. The existing CSS-only `.skeleton` utility in
 * globals.css stays for one transition loop; new code uses
 * `<Skeleton variant=… />`.
 */
const skeletonVariants = cva("bg-muted animate-pulse", {
  variants: {
    variant: {
      line: "h-4 w-full rounded-sm",
      card: "h-32 w-full rounded-md",
      image: "aspect-[16/10] w-full rounded-md",
      circle: "h-10 w-10 rounded-full",
      // `text` is rendered specially below — see component body
      text: "",
    },
  },
  defaultVariants: { variant: "line" },
});

export interface SkeletonProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof skeletonVariants> {}

export function Skeleton({ variant = "line", className, ...props }: SkeletonProps) {
  if (variant === "text") {
    // Three bars at decreasing widths — the canonical prose-block shape.
    return (
      <div
        aria-hidden="true"
        className={cn("flex flex-col gap-2", className)}
        {...props}
      >
        <div className="h-4 w-full rounded-sm bg-muted animate-pulse" />
        <div className="h-4 w-5/6 rounded-sm bg-muted animate-pulse" />
        <div className="h-4 w-3/4 rounded-sm bg-muted animate-pulse" />
      </div>
    );
  }
  return (
    <div
      aria-hidden="true"
      className={cn(skeletonVariants({ variant }), className)}
      {...props}
    />
  );
}
