"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { useT } from "@/lib/i18n/provider";

export default function NotFound() {
  const t = useT();
  return (
    <div className="container mx-auto flex max-w-md flex-col items-center gap-5 px-4 py-24 text-center">
      <Cartouche>{t("notFound.cartouche")}</Cartouche>
      <Glyph
        name="feather"
        size={56}
        mode="tint"
        className="text-gold/45"
      />
      <p className="font-display text-sm tracking-[0.4em] text-gold/70">{t("notFound.code")}</p>
      <h1 className="font-display text-4xl font-medium tracking-tight">{t("notFound.title")}</h1>
      <p className="font-body text-muted-foreground">{t("notFound.body")}</p>
      <Link href="/">
        <Button>{t("verifyCert.goHome")}</Button>
      </Link>
    </div>
  );
}
