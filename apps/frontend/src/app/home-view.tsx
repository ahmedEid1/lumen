"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CourseCard } from "@/components/course/course-card";
import type { Page, CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

type Pillar = {
  numberKey: MessageKey;
  titleKey: MessageKey;
  bodyKey: MessageKey;
};

const PILLARS: Pillar[] = [
  {
    numberKey: "home.deity.thoth",
    titleKey: "home.pillar1.title",
    bodyKey: "home.pillar1.body",
  },
  {
    numberKey: "home.deity.seshat",
    titleKey: "home.pillar2.title",
    bodyKey: "home.pillar2.body",
  },
  {
    numberKey: "home.deity.ptah",
    titleKey: "home.pillar3.title",
    bodyKey: "home.pillar3.body",
  },
];

export function HomeView({ featured }: { featured: Page<CourseListItem> }) {
  const t = useT();

  return (
    <div className="relative">
      {/* ── HERO ────────────────────────────────────────────────────── */}
      <Hero t={t} />

      {/* ── PILLARS ────────────────────────────────────────────────── */}
      <section className="container mx-auto px-6 py-32 sm:py-40">
        <div className="mx-auto mb-16 max-w-3xl text-center">
          <p className="reveal mb-4 font-body text-sm font-medium uppercase tracking-[0.18em] text-primary">
            {t("home.pillarsCartouche")}
          </p>
          <h2 className="reveal font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl md:text-6xl">
            {t("home.pillarsH2_1")}
            <br />
            <span className="text-muted-foreground italic">{t("home.pillarsH2_2")}</span>
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {PILLARS.map((p, i) => (
            <Pillar key={p.titleKey} t={t} pillar={p} delayMs={i * 80} />
          ))}
        </div>
      </section>

      {/* ── FEATURED COURSES ──────────────────────────────────────── */}
      <section className="border-t border-border/60 py-32 sm:py-40">
        <div className="container mx-auto mb-16 flex flex-col items-start justify-between gap-6 px-6 sm:flex-row sm:items-end">
          <div>
            <p className="reveal mb-4 font-body text-sm font-medium uppercase tracking-[0.18em] text-primary">
              {t("home.scrollCartouche")}
            </p>
            <h2 className="reveal font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">
              {t("home.scrollH2")}
            </h2>
          </div>
          <Link
            href="/courses"
            className="reveal inline-flex items-center gap-1 font-body text-sm font-medium text-foreground hover:text-primary"
          >
            {t("home.allScrolls")} <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        {featured.items.length === 0 ? (
          <div className="container mx-auto px-6">
            <div className="surface flex flex-col items-center gap-3 py-20 text-center">
              <p className="font-display text-xl italic text-muted-foreground">
                {t("home.emptyTitle")}
              </p>
              <p className="font-body text-sm text-muted-foreground">{t("home.emptyBody")}</p>
            </div>
          </div>
        ) : (
          <div className="container mx-auto grid gap-6 px-6 sm:grid-cols-2 lg:grid-cols-3">
            {featured.items.map((c, i) => (
              <div
                key={c.id}
                className="reveal"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <CourseCard course={c} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── CLOSING CTA ───────────────────────────────────────────── */}
      <section className="border-t border-border/60">
        <div className="container mx-auto flex flex-col items-center gap-8 px-6 py-32 text-center sm:py-40">
          <h2 className="reveal max-w-3xl font-display text-5xl leading-[1.02] tracking-tight sm:text-7xl">
            {t("home.ctaTitle")}
          </h2>
          <p className="reveal max-w-xl font-body text-lg leading-relaxed text-muted-foreground">
            {t("home.ctaBody")}
          </p>
          <div
            className="reveal flex flex-col gap-3 sm:flex-row"
            style={{ animationDelay: "120ms" }}
          >
            <Link href="/register">
              <Button size="lg" className="px-8">
                {t("home.beginApprenticeship")}
              </Button>
            </Link>
            <Link href="/courses">
              <Button size="lg" variant="ghost" className="px-8">
                {t("home.browseFirst")} <ArrowUpRight className="ms-1 h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

function Hero({ t }: { t: ReturnType<typeof useT> }) {
  return (
    <section className="relative mesh-bg overflow-hidden">
      <div className="container mx-auto flex min-h-[88vh] flex-col items-center justify-center gap-8 px-6 py-32 text-center">
        <p className="reveal inline-flex items-center gap-2 font-body text-sm font-medium uppercase tracking-[0.18em] text-primary">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary [animation:drift_2.4s_ease-in-out_infinite]" />
          {t("home.cartouche")}
        </p>

        <h1
          className="reveal max-w-6xl font-display text-[clamp(3.5rem,9vw,8rem)] font-normal leading-[0.95] tracking-tight"
          style={{ animationDelay: "60ms" }}
        >
          {t("home.heroTitle1")}
          <br />
          <span className="italic text-shine">{t("home.heroTitle2")}</span>
        </h1>

        <p
          className="reveal max-w-2xl text-balance font-body text-lg leading-relaxed text-muted-foreground sm:text-xl"
          style={{ animationDelay: "140ms" }}
        >
          {t("home.heroSubline")}
        </p>

        <div
          className="reveal mt-2 flex flex-col items-center gap-3 sm:flex-row"
          style={{ animationDelay: "220ms" }}
        >
          <Link href="/courses">
            <Button size="lg" className="px-8">
              {t("home.enterLibrary")} <ArrowRight className="ms-1 h-4 w-4" />
            </Button>
          </Link>
          <Link href="/register">
            <Button size="lg" variant="ghost" className="px-6">
              {t("home.inscribeYourself")}
            </Button>
          </Link>
        </div>
      </div>

      {/* Subtle scroll cue */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-8 flex justify-center"
        aria-hidden
      >
        <div className="h-8 w-px bg-gradient-to-b from-transparent via-muted-foreground/40 to-transparent [animation:drift_3s_ease-in-out_infinite]" />
      </div>
    </section>
  );
}

/**
 * Pillar card with a tiny 3D lift on pointer-move that follows the
 * cursor. The card leans toward the cursor with rotateX/Y, gets a
 * stronger shadow, and slightly lifts. Pointer-leave snaps it back.
 *
 * Falls back gracefully on touch devices (no pointer-move events
 * fire, so the card stays flat — which is the right behaviour).
 */
function Pillar({
  t,
  pillar,
  delayMs,
}: {
  t: ReturnType<typeof useT>;
  pillar: Pillar;
  delayMs: number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });

  function onMove(e: React.PointerEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    // -3deg..+3deg max — gentle, Apple-style not arcade.
    setTilt({ x: (py - 0.5) * -6, y: (px - 0.5) * 6 });
  }
  function onLeave() {
    setTilt({ x: 0, y: 0 });
  }

  return (
    <article
      ref={ref}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className="reveal surface group relative flex h-full flex-col p-8 transition-shadow duration-500 hover:shadow-[0_24px_48px_-16px_hsl(0_0%_0%/0.18),0_8px_24px_-12px_hsl(var(--primary)/0.18)]"
      style={{
        animationDelay: `${delayMs}ms`,
        transformStyle: "preserve-3d",
        transform: `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        transition: "transform 220ms cubic-bezier(0.22, 1, 0.36, 1)",
      }}
    >
      <p className="mb-6 font-mono text-xs font-medium uppercase tracking-[0.2em] text-primary">
        {t("home.underDeity", { deity: t(pillar.numberKey) })}
      </p>
      <h3 className="mb-4 font-display text-3xl leading-tight tracking-tight">
        {t(pillar.titleKey)}
      </h3>
      <p className="font-body text-base leading-relaxed text-muted-foreground">
        {t(pillar.bodyKey)}
      </p>
    </article>
  );
}
