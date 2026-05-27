"use client";

import { FileText } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { useT } from "@/lib/i18n/provider";

export function BlogIndex() {
  const t = useT();

  return (
    <div className="relative">
      <section className="border-b border-border">
        <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-10">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("blog.cartouche")}
          </p>
          <h1 className="font-display text-3xl font-medium leading-tight tracking-tight sm:text-4xl">
            {t("blog.title")}
          </h1>
          <p className="max-w-2xl font-body text-sm text-muted-foreground">
            {t("blog.subline")}
          </p>
        </div>
      </section>

      <section className="container mx-auto px-6 py-10">
        <EmptyState
          icon={FileText}
          title={t("blog.empty.title")}
          body={t("blog.empty.body")}
        />
      </section>
    </div>
  );
}
