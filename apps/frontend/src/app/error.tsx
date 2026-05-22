"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  const t = useT();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center gap-5 px-6 py-24 text-center">
      <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-destructive">
        {t("errorPage.cartouche")}
      </p>
      <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
        {t("errorPage.title")}
      </h1>
      <p className="font-body text-lg text-muted-foreground">{t("errorPage.body")}</p>
      <Button onClick={reset}>{t("common.tryAgain")}</Button>
    </div>
  );
}
