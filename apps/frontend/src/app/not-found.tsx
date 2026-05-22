"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

export default function NotFound() {
  const t = useT();
  return (
    <div className="container mx-auto flex max-w-md flex-col items-center gap-5 px-6 py-24 text-center">
      <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
        {t("notFound.cartouche")}
      </p>
      <p className="font-display text-sm tracking-[0.4em] text-muted-foreground">
        {t("notFound.code")}
      </p>
      <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
        {t("notFound.title")}
      </h1>
      <p className="font-body text-lg text-muted-foreground">{t("notFound.body")}</p>
      <Link href="/">
        <Button>{t("verifyCert.goHome")}</Button>
      </Link>
    </div>
  );
}
