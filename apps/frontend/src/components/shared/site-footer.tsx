"use client";

import { Glyph } from "@/components/lumen/glyph";
import { useT } from "@/lib/i18n/provider";

export function SiteFooter() {
  const t = useT();
  return (
    <footer className="border-t border-gold/15 bg-card/30">
      <div className="container mx-auto flex flex-col items-center justify-between gap-4 px-4 py-7 font-body text-sm text-muted-foreground sm:flex-row">
        <p className="inline-flex items-center gap-2.5">
          <Glyph name="ankh" size={14} mode="tint" className="text-gold/60" />
          {t("footer.copyright", { year: new Date().getFullYear() })}
        </p>
        <nav className="flex gap-5">
          <a
            className="transition-colors hover:text-gold"
            href="/docs"
          >
            {t("footer.docs")}
          </a>
          <a
            className="transition-colors hover:text-gold"
            href="https://github.com/ahmedEid1/E-Learning-Platform"
          >
            GitHub
          </a>
        </nav>
      </div>
    </footer>
  );
}
