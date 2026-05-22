"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

/**
 * Workbench 404.
 *
 * Mono "404" tag, display-face title, body copy, primary CTA back home.
 * Single bordered card on the page background — the same restraint as
 * the error boundary so unfamiliar surfaces feel like part of the same
 * product, not a marketing detour.
 */
export default function NotFound() {
  const t = useT();
  return (
    <div className="container mx-auto px-6 py-24">
      <div className="surface mx-auto max-w-md p-8">
        <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("notFound.code")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("notFound.title")}
        </h1>
        <p className="mt-3 font-body text-sm leading-relaxed text-muted-foreground">
          {t("notFound.body")}
        </p>
        <div className="mt-6">
          <Link href="/">
            <Button>{t("verifyCert.goHome")}</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
