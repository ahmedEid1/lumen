"use client";

/**
 * L30 — case-study long-form.
 *
 * Six sections, single column, generous line-height. Matches the
 * /eval/methodology shape so a recruiter reading the eval surface
 * lands in a familiar narrative voice.
 *
 *   1. Founding story (expanded from README opener)
 *   2. Architecture sketch (C4-ish, hand-drawn SVG)
 *   3. The turn lifecycle (sequence sketch)
 *   4. Prompt iteration + the failure mode that taught me grounding
 *   5. What I did not use (and why)
 *   6. Lessons + the closing CTA
 */

import { ArrowLeft, Mail } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

function Section({
  cartouche,
  heading,
  children,
}: {
  cartouche: string;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-b border-border py-10 last:border-b-0">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {cartouche}
      </p>
      <h2 className="mt-2 font-display text-xl leading-tight tracking-tight sm:text-2xl">
        {heading}
      </h2>
      <div className="mt-5 max-w-3xl space-y-4 font-body text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </section>
  );
}

/**
 * Tiny inline C4-style architecture sketch. SVG, no library — the
 * goal is "drawn on a napkin to make the relationships obvious",
 * not "polished diagram from documentation tooling".
 */
function ArchitectureSketch() {
  return (
    <svg
      viewBox="0 0 460 200"
      className="my-2 w-full max-w-2xl text-foreground"
      role="img"
      aria-label="Lumen architecture — Caddy edge, Next.js web, FastAPI API, Celery worker, Postgres+pgvector, Redis streams, LLM provider"
    >
      <defs>
        <marker
          id="arr"
          markerWidth="6"
          markerHeight="6"
          refX="5"
          refY="3"
          orient="auto"
        >
          <path d="M0,0 L6,3 L0,6 z" fill="currentColor" />
        </marker>
      </defs>
      {/* User */}
      <rect x="10" y="86" width="60" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="40" y="103" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">user</text>
      {/* Web */}
      <rect x="100" y="86" width="70" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="135" y="98" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">Next.js</text>
      <text x="135" y="109" textAnchor="middle"
        className="font-mono" fontSize="9" fill="currentColor" opacity="0.6">SSE consumer</text>
      {/* API */}
      <rect x="200" y="86" width="70" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="235" y="98" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">FastAPI</text>
      <text x="235" y="109" textAnchor="middle"
        className="font-mono" fontSize="9" fill="currentColor" opacity="0.6">enqueues turn</text>
      {/* Worker */}
      <rect x="300" y="40" width="70" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="335" y="52" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">Celery</text>
      <text x="335" y="63" textAnchor="middle"
        className="font-mono" fontSize="9" fill="currentColor" opacity="0.6">orchestrator</text>
      {/* DB */}
      <rect x="300" y="86" width="70" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="335" y="98" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">Postgres</text>
      <text x="335" y="109" textAnchor="middle"
        className="font-mono" fontSize="9" fill="currentColor" opacity="0.6">pgvector</text>
      {/* Redis */}
      <rect x="300" y="132" width="70" height="28" rx="4"
        fill="none" stroke="currentColor" />
      <text x="335" y="144" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">Redis</text>
      <text x="335" y="155" textAnchor="middle"
        className="font-mono" fontSize="9" fill="currentColor" opacity="0.6">streams + caps</text>
      {/* LLM */}
      <rect x="400" y="40" width="50" height="28" rx="4"
        fill="none" stroke="currentColor" strokeDasharray="3,3" />
      <text x="425" y="58" textAnchor="middle"
        className="font-mono" fontSize="10" fill="currentColor">LLM</text>
      {/* Arrows */}
      <line x1="70" y1="100" x2="98" y2="100"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="170" y1="100" x2="198" y2="100"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="270" y1="95" x2="298" y2="60"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="270" y1="105" x2="298" y2="100"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="335" y1="68" x2="335" y2="84"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="335" y1="114" x2="335" y2="130"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="370" y1="54" x2="398" y2="54"
        stroke="currentColor" strokeWidth="1" markerEnd="url(#arr)" />
      <line x1="135" y1="118" x2="335" y2="145"
        stroke="currentColor" strokeWidth="1" strokeDasharray="4,3" opacity="0.7" />
    </svg>
  );
}

export function CaseStudyView() {
  const t = useT();
  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <Link
          href="/"
          className="inline-flex w-fit items-center gap-1.5 font-mono text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden />
          {t("caseStudy.back")}
        </Link>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("caseStudy.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("caseStudy.headline")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("caseStudy.subline")}
        </p>
      </header>

      <Section
        cartouche={t("caseStudy.origin.cartouche")}
        heading={t("caseStudy.origin.heading")}
      >
        <p>{t("caseStudy.origin.p1")}</p>
        <p>{t("caseStudy.origin.p2")}</p>
        <p>{t("caseStudy.origin.p3")}</p>
      </Section>

      <Section
        cartouche={t("caseStudy.arch.cartouche")}
        heading={t("caseStudy.arch.heading")}
      >
        <p>{t("caseStudy.arch.intro")}</p>
        <ArchitectureSketch />
        <p>{t("caseStudy.arch.notes")}</p>
      </Section>

      <Section
        cartouche={t("caseStudy.turn.cartouche")}
        heading={t("caseStudy.turn.heading")}
      >
        <p>{t("caseStudy.turn.intro")}</p>
        <ol className="list-decimal space-y-1.5 ps-5">
          <li>{t("caseStudy.turn.step1")}</li>
          <li>{t("caseStudy.turn.step2")}</li>
          <li>{t("caseStudy.turn.step3")}</li>
          <li>{t("caseStudy.turn.step4")}</li>
          <li>{t("caseStudy.turn.step5")}</li>
        </ol>
        <p>{t("caseStudy.turn.tail")}</p>
      </Section>

      <Section
        cartouche={t("caseStudy.prompt.cartouche")}
        heading={t("caseStudy.prompt.heading")}
      >
        <p>{t("caseStudy.prompt.p1")}</p>
        <p>{t("caseStudy.prompt.p2")}</p>
        <p>{t("caseStudy.prompt.p3")}</p>
      </Section>

      <Section
        cartouche={t("caseStudy.notUsed.cartouche")}
        heading={t("caseStudy.notUsed.heading")}
      >
        <p>{t("caseStudy.notUsed.intro")}</p>
        <ul className="list-disc space-y-1.5 ps-5">
          <li>{t("caseStudy.notUsed.langchain")}</li>
          <li>{t("caseStudy.notUsed.fineTune")}</li>
          <li>{t("caseStudy.notUsed.vectorDB")}</li>
          <li>{t("caseStudy.notUsed.judge")}</li>
        </ul>
      </Section>

      <Section
        cartouche={t("caseStudy.lessons.cartouche")}
        heading={t("caseStudy.lessons.heading")}
      >
        <p>{t("caseStudy.lessons.p1")}</p>
        <p>{t("caseStudy.lessons.p2")}</p>
        <p>{t("caseStudy.lessons.p3")}</p>
      </Section>

      <footer className="mt-12 flex flex-col items-start gap-3 border-t border-border pt-8">
        <p className="font-body text-sm text-muted-foreground">
          {t("caseStudy.footer.body")}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/demo">
            <Button size="sm" variant="default" type="button">
              {t("caseStudy.footer.tryDemo")}
            </Button>
          </Link>
          <Link href="/eval">
            <Button size="sm" variant="outline" type="button">
              {t("caseStudy.footer.eval")}
            </Button>
          </Link>
          <a
            href="mailto:ahmedhobeishy.tools@gmail.com?subject=Lumen%20case-study%20conversation"
            className="inline-flex"
          >
            <Button size="sm" variant="ghost" type="button">
              <Mail className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("caseStudy.footer.email")}
            </Button>
          </a>
        </div>
      </footer>
    </div>
  );
}
