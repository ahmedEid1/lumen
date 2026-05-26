"use client";

import * as React from "react";
import Link from "next/link";
import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * Workbench LinkButton.
 *
 * Consumes `<Button asChild>` + Next's `<Link>` so the result is a
 * single `<a>` element with the button's visual chrome — no nested
 * `<a><button>` pair. Replaces the four `<Link><Button>…</Button></Link>`
 * sites the audit named (`reset-password/page.tsx:92`,
 * `verify-email/page.tsx:113`, `verify/[id]/page.tsx:105`,
 * `course-detail-view.tsx:370`), which produce nested-interactive
 * a11y warnings.
 *
 * For external links pass `external`; the underlying anchor swaps to
 * `<a target="_blank" rel="noopener noreferrer">`. Without `external`,
 * we use Next's `<Link>` for client-side navigation.
 */
export interface LinkButtonProps extends Omit<ButtonProps, "asChild"> {
  href: string;
  external?: boolean;
}

export const LinkButton = React.forwardRef<HTMLAnchorElement, LinkButtonProps>(
  ({ href, external, children, ...buttonProps }, ref) => {
    return (
      <Button asChild {...buttonProps}>
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
