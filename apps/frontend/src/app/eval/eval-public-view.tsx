"use client";

/**
 * L27 — public eval view component.
 *
 * Three sections, top-down:
 *   1. Cartouche + headline + sealed-run metadata strip.
 *   2. The worked example (canonical demo question + what its
 *      ideal answer + tool path look like — placeholder until a
 *      sealed run lands).
 *   3. Cards for admin-promoted runs, the adversarial section (not
 *      run yet), and the methodology link.
 *
 * No data → no fake numbers. While the query loads the page says so,
 * and with nothing promoted it says that, instead of promising a run.
 */

import { Clock, ExternalLink, Mail, ShieldCheck, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useEvalPublic, type PublicSuiteSummary } from "@/lib/api/eval-public";
import type { MessageKey } from "@/lib/i18n/messages/en";
import { useT } from "@/lib/i18n/provider";

const CANONICAL_QUESTION_SLUG = "ts-variance-canonical";

const CANONICAL_PROMPT =
  "I keep getting `Type 'string' is not assignable to type 'T'` on this function — here's my code, why does this happen and how do I fix it?";

const EXPECTED_TOOL_PATH = ["retriever", "code_runner"] as const;

// The public endpoint returns only the judge, so the setup of each
// promoted baseline report is named here, keyed by report id.
const BASELINE_SETUP: Partial<Record<string, MessageKey>> = {
  "tutor-baseline-20260528-014421": "eval.suites.baseline.tutor20260528",
};

export function EvalPublicView() {
  const t = useT();
  const evalQ = useEvalPublic();
  const promotedSuites: [string, PublicSuiteSummary][] = evalQ.data
    ? Object.entries(evalQ.data.suites).filter(
        (entry): entry is [string, PublicSuiteSummary] => entry[1] !== null,
      )
    : [];
  const hasPromoted = promotedSuites.length > 0;
  const loading = evalQ.isPending;
  return (
    <div className="container mx-auto max-w-5xl px-6 py-14">
      {/* Hero */}
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("eval.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("eval.headline")}
        </h1>
        <p className="max-w-3xl font-body text-sm text-muted-foreground">
          {t("eval.subline")}
        </p>
        {hasPromoted ? (
          <div
            className="mt-1 inline-flex w-fit items-center gap-2 rounded-md border border-border bg-muted/30 px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-foreground"
            data-testid="eval-sealed-live"
          >
            <Clock className="h-3 w-3 text-primary" aria-hidden />
            <span>
              {t("eval.sealedRunLive")} ·{" "}
              {promotedSuites[0][1].finished_at?.slice(0, 10) ?? "—"}
            </span>
          </div>
        ) : (
          <div
            className="mt-1 inline-flex w-fit items-center gap-2 rounded-md border border-dashed border-border bg-muted/30 px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-muted-foreground"
            data-testid={loading ? "eval-sealed-loading" : "eval-sealed-pending"}
          >
            <Clock className="h-3 w-3" aria-hidden />
            <span>{t(loading ? "eval.loading" : "eval.sealedRunPending")}</span>
          </div>
        )}
      </header>

      {/* Honest-numbers framing banner (F08) — additive, no logic change.
          Sits right under the hero (above the suite table) and reuses the
          page's surface card + cartouche/ShieldCheck design language. */}
      <section
        className="surface mb-10 p-6"
        aria-labelledby="eval-honest-numbers-heading"
        data-testid="eval-honest-numbers-banner"
      >
        <div className="mb-2 flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          <ShieldCheck className="h-3 w-3 text-primary" aria-hidden />
          <span id="eval-honest-numbers-heading">{t("eval.honest.heading")}</span>
        </div>
        <p className="max-w-3xl font-body text-sm leading-relaxed text-muted-foreground">
          {t("eval.honest.body")}
        </p>
      </section>

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

      {/* Suite trends — honest-empty until a sealed run is promoted */}
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
        {hasPromoted ? (
          <>
            <ul className="grid gap-3 sm:grid-cols-2">
              {promotedSuites.map(([name, summary]) => (
                <SuiteCard key={name} name={name} summary={summary} />
              ))}
            </ul>
            <p
              className="mt-4 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
              data-testid="eval-suites-caveat"
            >
              {t("eval.suites.caveat")}
            </p>
          </>
        ) : loading ? (
          <p
            className="font-body text-sm text-muted-foreground"
            data-testid="eval-suites-loading"
          >
            {t("eval.loading")}
          </p>
        ) : (
          <p
            className="font-body text-sm text-muted-foreground"
            data-testid="eval-suites-empty"
          >
            {t("eval.suites.empty")}
          </p>
        )}
      </section>

      {/* Adversarial probes — not run yet; never shows the prompts */}
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
          {/* Codex rescue: Button asChild to avoid <a><button> nesting. */}
          <Button asChild size="sm" variant="outline">
            <a href="/eval/methodology">
              <ExternalLink className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("eval.footer.methodology")}
            </a>
          </Button>
          <Button asChild size="sm" variant="default">
            <a href="mailto:ahmedhobeishy@gmail.com?subject=Lumen%20eval%20conversation">
              <Mail className="me-1.5 h-3.5 w-3.5" aria-hidden />
              {t("eval.footer.contact")}
            </a>
          </Button>
        </div>
      </footer>
    </div>
  );
}


/**
 * L41-followup — one suite's measured numbers, rendered as a card.
 *
 * Headline: mean_overall (the cross-axis average). Below that, the
 * three axes as labeled rows. mean_overall sits in [-5, 5] (deltas
 * are primary − baseline on a 0-5 judge scale); positive means
 * Lumen out-performs the baseline on that axis.
 */
function SuiteCard({
  name,
  summary,
}: {
  name: string;
  summary: PublicSuiteSummary;
}) {
  const t = useT();
  const fmt = (n: number | null | undefined) =>
    n === null || n === undefined ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2);
  const setupKey = BASELINE_SETUP[summary.report_id];
  return (
    <li
      className="rounded-md border border-border bg-muted/30 p-4"
      data-testid={`eval-suite-card-${name}`}
    >
      <div className="mb-2 flex items-baseline justify-between">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {name}
        </p>
        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          n={summary.items_judged ?? 0}
        </p>
      </div>
      <p className="mb-1 font-display text-2xl leading-none tracking-tight">
        Δ {fmt(summary.mean_overall)}
      </p>
      <p className="mb-3 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        {t("eval.suites.deltaCaption")}
      </p>
      {setupKey && (
        <p
          className="mb-3 font-body text-xs text-muted-foreground"
          data-testid={`eval-suite-setup-${name}`}
        >
          {t(setupKey)}
        </p>
      )}
      <dl className="grid grid-cols-3 gap-2 text-xs">
        {Object.entries(summary.axes).map(([axis, delta]) => (
          <div key={axis}>
            <dt className="font-mono uppercase tracking-wider text-muted-foreground">
              {axis}
            </dt>
            <dd className="font-mono text-foreground">{fmt(delta)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {t("eval.suites.judge")}: {summary.judge_model ?? "—"}
      </p>
    </li>
  );
}
