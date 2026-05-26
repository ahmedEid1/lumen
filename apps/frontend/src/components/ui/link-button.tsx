"use client";

import * as React from "react";
import Link from "next/link";
import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Workbench LinkButton.
 *
 * Consumes `<Button asChild>` + Next's `<Link>` so the result is a
 * single `<a>` element with the button's visual chrome — no nested
 * `<a><button>` pair. Replaces the four `<Link><Button>…</Button></Link>`
 * sites the audit named (`reset-password/page.tsx:92`,
 * `verify-email/page.tsx:113`, `verify/[id]/page.tsx:105`,
 * `course-detail-view.tsx:370`).
 *
 * For external links pass `external`; the underlying anchor swaps to
 * `<a target="_blank" rel="noopener noreferrer">`. Without `external`
 * we use Next's `<Link>` for client-side navigation.
 *
 * Disabled state: `<a>` does not match the `:disabled` pseudo-selector,
 * so `Button`'s `disabled:pointer-events-none` + `disabled:opacity-50`
 * Tailwind variants are no-ops when the rendered child is an anchor.
 * `<LinkButton disabled>` therefore:
 *   - renders a bare `<a>` with NO `href` (navigation impossible)
 *   - sets `aria-disabled="true"` (AT announces the disabled state)
 *   - sets `tabIndex={-1}` (keyboard focus skips the disabled link)
 *   - prevents default on click (defence-in-depth; if some future
 *     edit accidentally re-adds an href, this still blocks the nav)
 *   - applies `opacity-50 pointer-events-none` via the component's
 *     own className so the visual disabled state matches Button's
 * Pre-fix this was Codex rescue #1's only finding — see
 * `docs/redesign/codex-review-loops-1-to-3.md`.
 */
export interface LinkButtonProps extends Omit<ButtonProps, "asChild"> {
  href: string;
  external?: boolean;
}

export const LinkButton = React.forwardRef<HTMLAnchorElement, LinkButtonProps>(
  ({ href, external, children, disabled, className, ...buttonProps }, ref) => {
    if (disabled) {
      return (
        <Button
          asChild
          className={cn("pointer-events-none opacity-50", className)}
          {...buttonProps}
        >
          <a
            ref={ref}
            aria-disabled="true"
            tabIndex={-1}
            role="link"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            {children}
          </a>
        </Button>
      );
    }

    return (
      <Button asChild className={className} {...buttonProps}>
        {external ? (
          <a
            ref={ref}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {children}
          </a>
        ) : (
          <Link ref={ref} href={href}>
            {children}
          </Link>
        )}
      </Button>
    );
  },
);
LinkButton.displayName = "LinkButton";
