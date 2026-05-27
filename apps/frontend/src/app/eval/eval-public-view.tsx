"use client";

/**
 * L27 — public eval view component.
 *
 * Three sections, top-down:
 *   1. Cartouche + headline + sealed-run metadata strip.
 *   2. The worked example (canonical demo question + what its
 *      ideal answer + tool path look like — placeholder until a
 *      sealed run lands).
 *   3. Suite-level cards (currently honest-empty), the adversarial
 *      refusal-rate placeholder, and the methodology link.
 *
 * No data yet → no fake numbers. The page renders honest-empty
 * states with explicit "pending" badges so a recruiter reading
 * doesn't see hallucinated metrics. L28 will pair this with the
 * methodology page where the framing is the focus.
 */

import { Clock, ExternalLink, Mail, ShieldCheck, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";

const CANONICAL_QUESTION_SLUG = "ts-variance-canonical";

const CANONICAL_PROMPT =
  "I keep getting `Type 'string' is not assignable to type 'T'` on this function — here's my code, why does this happen and how do I fix it?";

const EXPECTED_TOOL_PATH = ["retriever", "code_runner"] as const;

export function EvalPublicView() {
  const t = useT();
  return (
    <div className="container mx-auto max-w-5xl px-6 py-14">
      {/* Hero */}
      <header className="mb-12 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("eval.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("eval.headline")}
        </h1>
        <p className="max-w-3xl font-body text-sm text-muted-foreground">
          {t("eval.subline")}
        </p>
        <div
          className="mt-1 inline-flex w-fit items-center gap-2 rounded-md border border-dashed border-border bg-muted/30 px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-muted-foreground"
          data-testid="eval-sealed-pending"
        >
          <Clock className="h-3 w-3" aria-hidden />
          <span>{t("eval.sealedRunPending")}</span>
        </div>
      </header>

      {/* Worked example */}
      <section
        className="surface mb-10 p-6"
        aria-labelledby="eval-worked-heading"
      >
        <div className="mb-4 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          <Sparkles className="h-3 w-3 text-primary" aria-hidden />
          <span id="eval-worked-heading">
            {t("eval.workedExample.cartouche")}
          </span>
        </div>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          {t("eval.workedExample.heading")}
        </h2>

        <div className="mb-4 rounded-md border border-border bg-muted/30 p-4 font-body text-sm">
          <p className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {t("eval.workedExample.questionLabel")} ·{" "}
            <span className="text-foreground">{CANONICAL_QUESTION_SLUG}</span>
          </p>
          <p>{CANONICAL_PROMPT}</p>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <div>
            <dt className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              {t("eval.workedExample.toolPathLabel")}
            </dt>
            <dd>
              <ul className="flex flex-wrap gap-1">
                {EXPECTED_TOOL_PATH.map((tool) => (
                  <li
                    key={tool}
                    className="rounded-md border border-border bg-muted/20 px-2 py-0.5 font-mono text-xs text-foreground"
                  >
                    {tool}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
          <div>
            <dt className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              {t("eval.workedExample.measurementLabel")}
            </dt>
            <dd className="font-mono text-xs text-muted-foreground">
              {t("eval.workedExample.measurementPending")}
            </dd>
          </div>
        </dl>
      </section>

      {/* Suite trends — placeholder while sealed runs are pending */}
      <section
        className="surface mb-10 p-6"
        aria-labelledby="eval-suites-heading"
      >
        <div className="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          <span id="eval-suites-heading">{t("eval.suites.cartouche")}</span>
        </div>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          {t("eval.suites.heading")}
        </h2>
        <p className="font-body text-sm text-muted-foreground">
          {t("eval.suites.empty")}
        </p>
      </section>

      {/* Adversarial refusal-rate — placeholder; never shows the prompts */}
      <section
        className="surface mb-10 p-6"
        aria-labelledby="eval-adversarial-heading"
      >
        <div className="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          <ShieldCheck className="h-3 w-3 text-primary" aria-hidden />
          <span id="eval-adversarial-heading">
            {t("eval.adversarial.cartouche")}
          </span>
        </div>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          {t("eval.adversarial.heading")}
        </h2>
        <p className="font-body text-sm text-muted-foreground">
          {t("eval.adversarial.body")}
        </p>
        <p className="mt-3 font-mono text-xs text-muted-foreground">
          {t("eval.adversarial.measurementPending")}
        </p>
      </section>

      {/* Footer — methodology link + contact CTA */}
      <footer className="mt-12 flex flex-col items-start gap-3 border-t border-border pt-8">
        <p className="font-body text-sm text-muted-foreground">
          {t("eval.footer.body")}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <a href="/eval/methodology" className="inline-flex">
            <Button size="sm" variant="outline" type="button">
              <ExternalLink className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("eval.footer.methodology")}
            </Button>
          </a>
          <a
            href="mailto:ahmedhobeishy.tools@gmail.com?subject=Lumen%20eval%20conversation"
            className="inline-flex"
          >
            <Button size="sm" variant="default" type="button">
              <Mail className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("eval.footer.contact")}
            </Button>
          </a>
        </div>
      </footer>
    </div>
  );
}
