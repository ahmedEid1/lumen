"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { useT } from "@/lib/i18n/provider";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  const t = useT();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center gap-5 px-4 py-24 text-center">
      <Cartouche>{t("errorPage.cartouche")}</Cartouche>
      <Glyph
        name="feather"
        size={56}
        mode="tint"
        className="text-destructive/70 drop-shadow-[0_0_14px_hsl(var(--carnelian)/0.4)]"
      />
      <h1 className="font-display text-4xl font-medium tracking-tight">{t("errorPage.title")}</h1>
      <p className="font-body text-muted-foreground">{t("errorPage.body")}</p>
      <Button onClick={reset}>{t("common.tryAgain")}</Button>
    </div>
  );
}
