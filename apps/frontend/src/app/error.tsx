"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/ui/link-button";
import { useT } from "@/lib/i18n/provider";

/**
 * Workbench error boundary.
 *
 * A single bordered card on the page background; the `digest` (when
 * Next.js attaches one to a server error) renders as a mono ID so it's
 * copyable into a bug report. Retry is the primary CTA, "go home" is a
 * bordered ghost link. No marketing copy, no illustration, no shadow.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useT();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="container mx-auto px-6 py-24">
      <div className="surface mx-auto max-w-md p-8">
        <p className="mb-3 font-mono text-xs uppercase tracking-wider text-destructive">
          {t("errorPage.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("errorPage.title")}
        </h1>
        <p className="mt-3 font-body text-sm leading-relaxed text-muted-foreground">
          {t("errorPage.body")}
        </p>
        {error.digest ? (
          <p className="mt-4 font-mono text-xs text-muted-foreground">{error.digest}</p>
        ) : null}
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Button onClick={reset}>{t("common.tryAgain")}</Button>
          <LinkButton href="/" variant="ghost">
            {t("verifyCert.goHome")}
          </LinkButton>
        </div>
      </div>
    </div>
  );
}
