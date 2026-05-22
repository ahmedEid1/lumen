"use client";

import { useT } from "@/lib/i18n/provider";

export function SiteFooter() {
  const t = useT();
  return (
    <footer className="border-t border-border">
      <div className="container mx-auto flex flex-col items-center justify-between gap-4 px-6 py-8 font-body text-sm text-muted-foreground sm:flex-row">
        <p>{t("footer.copyright", { year: new Date().getFullYear() })}</p>
        <nav className="flex gap-6">
          <a
            className="transition-colors duration-[160ms] hover:text-foreground"
            href="/docs"
          >
            {t("footer.docs")}
          </a>
          <a
            className="transition-colors duration-[160ms] hover:text-foreground"
            href="https://github.com/ahmedEid1/E-Learning-Platform"
          >
            GitHub
          </a>
        </nav>
      </div>
    </footer>
  );
}
