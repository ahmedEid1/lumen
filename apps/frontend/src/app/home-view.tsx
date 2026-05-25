"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CourseCard } from "@/components/course/course-card";
import type { Page, CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Workbench home page.
 *
 * Linear / Raycast / Vercel-dashboard density. Dark-first. Headlines
 * are left-aligned page labels, not centered marketing claims. Borders
 * do the elevation work — no shadows, no mesh chrome, no 3D tilt, no
 * scroll-reveal stagger. Lime accent lives on the primary CTA in the
 * hero and the primary CTA in the closing band; every other surface is
 * a bordered ghost. Eyebrow cartouches are mono uppercase muted, the
 * way Linear labels a section.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

type Pillar = {
  numberKey: MessageKey;
  titleKey: MessageKey;
  bodyKey: MessageKey;
};

const PILLARS: Pillar[] = [
  {
    numberKey: "home.pillar1.number",
    titleKey: "home.pillar1.title",
    bodyKey: "home.pillar1.body",
  },
  {
    numberKey: "home.pillar2.number",
    titleKey: "home.pillar2.title",
    bodyKey: "home.pillar2.body",
  },
  {
    numberKey: "home.pillar3.number",
    titleKey: "home.pillar3.title",
    bodyKey: "home.pillar3.body",
  },
];

export function HomeView({ featured }: { featured: Page<CourseListItem> }) {
  const t = useT();

  return (
    <div className="bg-background">
      <Hero t={t} />

      {/* Pillars — flat surface cards on the page background. Section
          header is a left-aligned label, not a centered claim. */}
      <section className="border-t border-border">
        <div className="container mx-auto px-6 py-24 sm:py-32">
          <div className="mb-12 max-w-2xl">
            <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {t("home.pillarsCartouche")}
            </p>
            <h2 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
              {t("home.pillarsH2_1")}{" "}
              <span className="text-muted-foreground">{t("home.pillarsH2_2")}</span>
            </h2>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {PILLARS.map((p) => (
              <PillarCard key={p.titleKey} t={t} pillar={p} />
            ))}
          </div>
        </div>
      </section>

      {/* Featured catalogue — section header is left-aligned, the
          courses grid keeps its existing card primitive. No reveal
          stagger; the cards land as a static grid. */}
      <section className="border-t border-border">
        <div className="container mx-auto px-6 py-24 sm:py-32">
          <div className="mb-10 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
            <div className="max-w-2xl">
              <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {t("home.scrollCartouche")}
              </p>
              <h2 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
                {t("home.scrollH2")}
              </h2>
            </div>
            <Link
              href="/courses"
              className="inline-flex items-center gap-1 font-body text-sm text-muted-foreground transition-colors duration-[160ms] hover:text-foreground focus-visible:text-foreground"
            >
              {t("home.allScrolls")} <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {featured.items.length === 0 ? (
            <div className="surface flex flex-col items-start gap-2 p-8">
              <p className="font-display text-lg tracking-tight">
                {t("home.emptyTitle")}
              </p>
              <p className="font-body text-sm text-muted-foreground">
                {t("home.emptyBody")}
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {featured.items.map((c) => (
                <CourseCard key={c.id} course={c} />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Closing CTA — left-aligned, single primary action, ghost
          secondary. No centered marketing hero. */}
      <section className="border-t border-border">
        <div className="container mx-auto px-6 py-24 sm:py-32">
          <div className="max-w-2xl">
            <h2 className="font-display text-4xl leading-tight tracking-tight sm:text-5xl">
              {t("home.ctaTitle")}
            </h2>
            <p className="mt-4 font-body text-base leading-relaxed text-muted-foreground sm:text-lg">
              {t("home.ctaBody")}
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link href="/register">
                <Button size="lg">{t("home.beginApprenticeship")}</Button>
              </Link>
              <Link href="/courses">
                <Button size="lg" variant="ghost">
                  {t("home.browseFirst")}
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

/**
 * Hero — left-aligned 48-72px headline on a flat background. The
 * primary CTA is the screen's single lime accent; the secondary action
 * is a bordered ghost. No mesh, no text-shine, no drift animation.
 */
function Hero({ t }: { t: ReturnType<typeof useT> }) {
  return (
    <section className="border-b border-border">
      <div className="container mx-auto px-6 py-24 sm:py-32 lg:py-40">
        <div className="max-w-3xl">
          <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("home.cartouche")}
          </p>
          <h1 className="font-display text-5xl leading-[1.05] tracking-tight sm:text-6xl md:text-7xl">
            {t("home.heroTitle1")}{" "}
            <span className="text-muted-foreground">{t("home.heroTitle2")}</span>
          </h1>
          <p className="mt-6 max-w-xl font-body text-base leading-relaxed text-muted-foreground sm:text-lg">
            {t("home.heroSubline")}
          </p>
          <div className="mt-10 flex flex-col gap-3 sm:flex-row">
            <Link href="/courses">
              <Button size="lg">
                {t("home.enterLibrary")} <ArrowRight className="ms-1 h-4 w-4" />
              </Button>
            </Link>
            <Link href="/register">
              <Button size="lg" variant="ghost">
                {t("home.inscribeYourself")}
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * Pillar card — flat surface with a mono numeric eyebrow (`01`/`02`/
 * `03`), a tight display headline, and body copy. Single border, no
 * shadow, no tilt; padding is p-5 to stay on the 8px grid.
 */
function PillarCard({
  t,
  pillar,
}: {
  t: ReturnType<typeof useT>;
  pillar: Pillar;
}) {
  return (
    <article className="surface flex h-full flex-col p-5">
      <p className="mb-5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {t(pillar.numberKey)}
      </p>
      <h3 className="mb-3 font-display text-xl leading-tight tracking-tight">
        {t(pillar.titleKey)}
      </h3>
      <p className="font-body text-sm leading-relaxed text-muted-foreground">
        {t(pillar.bodyKey)}
      </p>
    </article>
  );
}
