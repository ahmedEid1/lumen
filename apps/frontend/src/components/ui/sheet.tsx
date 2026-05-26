"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Workbench Sheet.
 *
 * Side-anchored Dialog. Shares Radix Dialog's a11y guarantees
 * (focus trap, aria-modal, Escape, click-outside) but slides in
 * from a screen edge instead of centering. Lands a Workbench
 * mobile menu, future studio side-panels, and the eventual
 * settings drawer — all surfaces flagged in AUDIT.md §2 (Sheet row).
 *
 * `side` controls anchoring + slide-in direction. Animation rules
 * live in `globals.css` keyed off `data-wb-sheet-content` +
 * `data-side` + Radix `data-state="open"`. Same 160ms / ease-out-quart
 * timing as Dialog.
 *
 * Sheet re-exports DialogPrimitive's Title / Description / Close
 * under `Sheet*` names so consumers don't import Dialog parts.
 */

const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetClose = DialogPrimitive.Close;
const SheetPortal = DialogPrimitive.Portal;

const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    data-wb-dialog-overlay=""
    className={cn(
      "fixed inset-0 z-overlay bg-foreground/30 backdrop-blur-[2px]",
      className,
    )}
    {...props}
  />
));
SheetOverlay.displayName = DialogPrimitive.Overlay.displayName;

type Side = "right" | "left" | "top" | "bottom";

const sidePositioning: Record<Side, string> = {
  right: "inset-y-0 end-0 h-full w-3/4 max-w-sm border-s",
  left: "inset-y-0 start-0 h-full w-3/4 max-w-sm border-e",
  top: "inset-x-0 top-0 w-full max-h-[85vh] border-b",
  bottom: "inset-x-0 bottom-0 w-full max-h-[85vh] border-t",
};

type SheetContentProps = React.ComponentPropsWithoutRef<
  typeof DialogPrimitive.Content
> & {
  side?: Side;
  srLabelClose?: string;
  hideCloseButton?: boolean;
};

const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  SheetContentProps
>(
  (
    {
      className,
      children,
      side = "right",
      srLabelClose = "Close",
      hideCloseButton,
      ...props
    },
    ref,
  ) => (
    <SheetPortal>
      <SheetOverlay />
      <DialogPrimitive.Content
        ref={ref}
        data-wb-sheet-content=""
        data-side={side}
        className={cn(
          "fixed z-modal bg-card text-card-foreground border-border",
          "p-6 focus:outline-none",
          sidePositioning[side],
          className,
        )}
        {...props}
      >
        {children}
        {!hideCloseButton && (
          <DialogPrimitive.Close
            className={cn(
              "absolute end-4 top-4 inline-grid h-7 w-7 place-items-center rounded-md",
              "text-muted-foreground transition-colors duration-base",
              "hover:bg-muted hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            )}
          >
            <X className="h-4 w-4" aria-hidden />
            <span className="sr-only">{srLabelClose}</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </SheetPortal>
  ),
);
SheetContent.displayName = DialogPrimitive.Content.displayName;

function SheetHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("mb-4 flex flex-col gap-1.5 text-start", className)}
      {...props}
    />
  );
}
SheetHeader.displayName = "SheetHeader";

function SheetFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    />
  );
}
SheetFooter.displayName = "SheetFooter";

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("font-display text-lg leading-tight tracking-tight", className)}
    {...props}
  />
));
SheetTitle.displayName = DialogPrimitive.Title.displayName;

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("font-body text-sm text-muted-foreground", className)}
    {...props}
  />
));
SheetDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetPortal,
  SheetOverlay,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
};
