"use client";

/**
 * L28 — eval methodology view.
 *
 * Long-form narrative, broken into five sections:
 *  1. What we measure
 *  2. How (LLM-as-judge rubric)
 *  3. Adversarial corpus design (no prompts disclosed)
 *  4. Known limits
 *  5. What I'd do differently at scale
 *
 * Workbench posture — generous line-height, cartouche per section,
 * mono pills for the rubric axes, no diagrams (yet). Recruiters
 * read top-to-bottom; the page is one column so a phone scroll
 * doesn't break the flow.
 */

import { useT } from "@/lib/i18n/provider";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

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
    <section className="border-b border-border py-8 last:border-b-0">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {cartouche}
      </p>
      <h2 className="mt-2 font-display text-xl leading-tight tracking-tight sm:text-2xl">
        {heading}
      </h2>
      <div className="mt-4 max-w-3xl space-y-4 font-body text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </section>
  );
}

function MonoPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-md border border-border bg-muted/30 px-2 py-0.5 font-mono text-xs text-foreground">
      {children}
    </span>
  );
}

export function EvalMethodologyView() {
  const t = useT();
  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <Link
          href="/eval"
          className="inline-flex w-fit items-center gap-1.5 font-mono text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden />
          {t("evalMethodology.back")}
        </Link>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("evalMethodology.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("evalMethodology.headline")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("evalMethodology.subline")}
        </p>
      </header>

      <Section
        cartouche={t("evalMethodology.what.cartouche")}
        heading={t("evalMethodology.what.heading")}
      >
        <p>{t("evalMethodology.what.intro")}</p>
        <ul className="list-disc space-y-1 ps-5">
          <li>
            <MonoPill>grounding</MonoPill>{" "}
            {t("evalMethodology.what.axis.grounding")}
          </li>
          <li>
            <MonoPill>accuracy</MonoPill>{" "}
            {t("evalMethodology.what.axis.accuracy")}
          </li>
          <li>
            <MonoPill>style</MonoPill> {t("evalMethodology.what.axis.style")}
          </li>
        </ul>
        <p>{t("evalMethodology.what.tail")}</p>
      </Section>

      <Section
        cartouche={t("evalMethodology.how.cartouche")}
        heading={t("evalMethodology.how.heading")}
      >
        <p>{t("evalMethodology.how.intro")}</p>
        <p>{t("evalMethodology.how.judge")}</p>
        <p>{t("evalMethodology.how.bias")}</p>
      </Section>

      <Section
        cartouche={t("evalMethodology.adv.cartouche")}
        heading={t("evalMethodology.adv.heading")}
      >
        <p>{t("evalMethodology.adv.intro")}</p>
        <p>{t("evalMethodology.adv.heuristic")}</p>
        <p className="flex items-start gap-2 font-body text-sm">
          <ShieldCheck
            className="mt-0.5 h-4 w-4 shrink-0 text-primary"
            aria-hidden
          />
          <span>{t("evalMethodology.adv.disclosure")}</span>
        </p>
      </Section>

      <Section
        cartouche={t("evalMethodology.limits.cartouche")}
        heading={t("evalMethodology.limits.heading")}
      >
        <p>{t("evalMethodology.limits.judgeOnLLM")}</p>
        <p>{t("evalMethodology.limits.smallN")}</p>
        <p>{t("evalMethodology.limits.snapshot")}</p>
      </Section>

      <Section
        cartouche={t("evalMethodology.scale.cartouche")}
        heading={t("evalMethodology.scale.heading")}
      >
        <p>{t("evalMethodology.scale.humanGraders")}</p>
        <p>{t("evalMethodology.scale.continuousJudge")}</p>
        <p>{t("evalMethodology.scale.adversarialRotation")}</p>
      </Section>

      <footer className="mt-10 flex flex-col items-start gap-3 border-t border-border pt-8">
        <p className="font-body text-sm text-muted-foreground">
          {t("evalMethodology.footer.body")}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {/* Codex rescue: Button asChild to avoid <a><button> nesting. */}
          <Button asChild size="sm" variant="outline">
            <Link href="/eval">{t("evalMethodology.footer.backToEval")}</Link>
          </Button>
          <Button asChild size="sm" variant="default">
            <a href="mailto:ahmedhobeishy.tools@gmail.com?subject=Lumen%20eval%20methodology%20question">
              {t("evalMethodology.footer.contact")}
            </a>
          </Button>
        </div>
      </footer>
    </div>
  );
}
