"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CourseCard } from "@/components/course/course-card";
import { Glyph, type GlyphName } from "@/components/lumen/glyph";
import { Cartouche } from "@/components/lumen/cartouche";
import { PapyrusBg } from "@/components/lumen/papyrus-bg";
import { Torchlight } from "@/components/lumen/torchlight";
import { EyeDivider } from "@/components/lumen/eye-divider";
import type { Page, CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

type Pillar = {
  glyph: GlyphName;
  deityKey: MessageKey;
  titleKey: MessageKey;
  bodyKey: MessageKey;
};

const PILLARS: Pillar[] = [
  {
    glyph: "feather",
    deityKey: "home.deity.thoth",
    titleKey: "home.pillar1.title",
    bodyKey: "home.pillar1.body",
  },
  {
    glyph: "ankh",
    deityKey: "home.deity.seshat",
    titleKey: "home.pillar2.title",
    bodyKey: "home.pillar2.body",
  },
  {
    glyph: "djed",
    deityKey: "home.deity.ptah",
    titleKey: "home.pillar3.title",
    bodyKey: "home.pillar3.body",
  },
];

export function HomeView({ featured }: { featured: Page<CourseListItem> }) {
  const t = useT();

  return (
    <div className="relative">
      {/* ── HERO ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <PapyrusBg />
        <Torchlight intensity={0.35} />

        {/* corner cartouches — bracket the hero like the four sons of Horus */}
        <CornerPiece className="left-4 top-4" />
        <CornerPiece className="right-4 top-4 rotate-90" />
        <CornerPiece className="bottom-4 left-4 -rotate-90" />
        <CornerPiece className="bottom-4 right-4 rotate-180" />

        <div className="container mx-auto flex min-h-[78vh] flex-col items-center justify-center gap-8 px-4 py-24 text-center">
          <Cartouche className="reveal">{t("home.cartouche")}</Cartouche>

          <h1
            className="reveal max-w-5xl font-display text-[clamp(3rem,8vw,7rem)] font-medium leading-[0.95] tracking-tight ink-shadow"
            style={{ fontVariationSettings: '"opsz" 144, "SOFT" 25' }}
          >
            {t("home.heroTitle1")}
            <br />
            <span className="text-gold-gradient italic [animation:gold-shimmer_8s_ease-in-out_infinite]">
              {t("home.heroTitle2")}
            </span>
          </h1>

          <p
            className="reveal max-w-2xl text-balance font-body text-lg leading-relaxed text-muted-foreground sm:text-xl"
            style={{ animationDelay: "120ms" }}
          >
            {t("home.heroSubline")}
          </p>

          <div
            className="reveal mt-2 flex flex-col gap-3 sm:flex-row"
            style={{ animationDelay: "200ms" }}
          >
            <Link href="/courses">
              <Button size="lg" className="px-8">
                {t("home.enterLibrary")} <ArrowRight className="ms-1 h-4 w-4" />
              </Button>
            </Link>
            <Link href="/register">
              <Button size="lg" variant="outline" className="px-8">
                {t("home.inscribeYourself")}
              </Button>
            </Link>
          </div>

          {/* glyph line — purely decorative trail of six knowledge marks */}
          <div
            className="reveal mt-8 flex items-center gap-5 text-gold/55"
            style={{ animationDelay: "280ms" }}
            aria-hidden
          >
            {(["eye", "ankh", "djed", "feather", "was", "sun-disk"] as GlyphName[]).map(
              (g, i) => (
                <Glyph
                  key={g}
                  name={g}
                  size={26}
                  mode="tint"
                  className="transition-transform hover:-translate-y-1 hover:text-gold"
                  style={{ animation: `drift 5s ease-in-out ${i * 0.4}s infinite` }}
                />
              ),
            )}
          </div>
        </div>

        {/* scroll cue */}
        <div
          className="pointer-events-none absolute inset-x-0 bottom-6 flex justify-center text-gold/40"
          aria-hidden
        >
          <span className="flex h-9 w-5 items-start justify-center rounded-full border border-gold/30 p-1">
            <span className="block h-2 w-px animate-bounce rounded-full bg-gold/60" />
          </span>
        </div>
      </section>

      {/* ── THREE GIFTS OF THOTH ──────────────────────────────────── */}
      <section className="container mx-auto px-4 py-24">
        <div className="mb-14 flex flex-col items-center gap-4 text-center">
          <Cartouche>{t("home.pillarsCartouche")}</Cartouche>
          <h2 className="reveal max-w-2xl font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
            {t("home.pillarsH2_1")}
            <br />
            <span className="text-muted-foreground italic">{t("home.pillarsH2_2")}</span>
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {PILLARS.map((p, i) => (
            <article
              key={p.titleKey}
              className="reveal group relative flex flex-col items-center overflow-hidden rounded-md border border-border bg-card p-8 text-center transition-all duration-500 hover:-translate-y-1 hover:border-gold/40 scroll-paper"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              {/* obelisk pinnacle — thin gold cap */}
              <div className="absolute inset-x-12 top-0 h-px bg-gradient-to-r from-transparent via-gold/60 to-transparent" />

              <div className="mb-6 grid h-14 w-14 place-items-center rounded-full border border-gold/30 bg-background/60 text-gold transition-all duration-500 group-hover:[animation:pulse-ring_1.6s_ease-out_infinite]">
                <Glyph name={p.glyph} size={28} />
              </div>

              <p className="mb-2 text-[0.7rem] uppercase tracking-[0.32em] text-gold/70">
                {t("home.underDeity", { deity: t(p.deityKey) })}
              </p>
              <h3 className="mb-3 font-display text-2xl font-medium leading-snug">
                {t(p.titleKey)}
              </h3>
              <p className="font-body text-sm leading-relaxed text-muted-foreground">
                {t(p.bodyKey)}
              </p>
            </article>
          ))}
        </div>
      </section>

      <div className="container mx-auto px-4">
        <EyeDivider className="my-2" />
      </div>

      {/* ── LATEST SCROLLS ────────────────────────────────────────── */}
      <section className="container mx-auto px-4 py-24">
        <div className="mb-10 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
          <div className="flex flex-col gap-3">
            <Cartouche>{t("home.scrollCartouche")}</Cartouche>
            <h2 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
              {t("home.scrollH2")}
            </h2>
          </div>
          <Link href="/courses">
            <Button variant="outline" size="sm">
              {t("home.allScrolls")} <ArrowRight className="ms-1 h-4 w-4" />
            </Button>
          </Link>
        </div>

        {featured.items.length === 0 ? (
          <div className="rounded-md border border-dashed border-gold/30 bg-card/40 p-16 text-center scroll-paper">
            <Glyph
              name="feather"
              size={56}
              mode="tint"
              className="mx-auto mb-4 text-gold/40"
            />
            <p className="font-display text-xl italic text-muted-foreground">
              {t("home.emptyTitle")}
            </p>
            <p className="mt-2 font-body text-sm text-muted-foreground">
              {t("home.emptyBody")}
            </p>
          </div>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {featured.items.map((c, i) => (
              <div key={c.id} className="reveal" style={{ animationDelay: `${i * 60}ms` }}>
                <CourseCard course={c} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── CLOSING CTA — APPRENTICE TO THE MASTERS ──────────────── */}
      <section className="relative overflow-hidden border-t border-gold/15 bg-card/40">
        <div
          className="absolute inset-0 -z-10 opacity-30"
          style={{
            background:
              "radial-gradient(circle at 50% 0%, hsl(var(--gold-leaf) / 0.25), transparent 55%)",
          }}
          aria-hidden
        />
        <div className="container mx-auto flex flex-col items-center gap-6 px-4 py-24 text-center">
          <Glyph
            name="aten"
            size={84}
            mode="art"
            className="drop-shadow-[0_0_24px_hsl(var(--gold-leaf)/0.55)]"
          />
          <h2 className="reveal max-w-3xl font-display text-4xl font-medium leading-tight tracking-tight sm:text-6xl">
            {t("home.ctaTitle")}
          </h2>
          <p className="reveal max-w-xl text-balance font-body text-lg text-muted-foreground">
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
              <Button size="lg" variant="outline" className="px-8">
                {t("home.browseFirst")}
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

/** Decorative corner brackets framing the hero. */
function CornerPiece({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute h-14 w-14 text-gold/45 ${className}`}
    >
      <svg viewBox="0 0 56 56" className="h-full w-full" fill="none">
        <path
          d="M2 18 L2 2 L18 2"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
        />
        <circle cx="2" cy="2" r="1.6" fill="currentColor" />
        <path d="M8 8 L14 14" stroke="currentColor" strokeWidth="0.7" strokeLinecap="round" />
      </svg>
    </div>
  );
}
