"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ArrowRight } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { OnboardingTour } from "@/components/onboarding/onboarding-tour";
import { Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { learnerSteps } from "@/lib/onboarding/steps";

/**
 * Dashboard — Workbench repaint.
 *
 * Left-aligned welcome label (display, ~32-40px, label-like rather than
 * marketing-large). In-progress is a dense surface card grid; completed
 * is a bordered list of rows (not cards) — Workbench rule that finished
 * things should occupy less weight than active ones. Certificate links
 * are lime text with a small arrow icon, the screen's single accent
 * lives on the certificate links plus the progress bar fill.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function DashboardPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();
  const enrollmentsQ = useQuery({ queryKey: qk.enrollments, queryFn: () => Me.enrollments() });

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard");
  }, [ready, user, router]);

  if (!ready || !user) return null;

  const enrollments = enrollmentsQ.data ?? [];
  const inProgress = enrollments.filter((e) => !e.completed_at);
  const done = enrollments.filter((e) => e.completed_at);
  const firstName = user.full_name.split(" ")[0] || user.full_name;

  return (
    <div className="container mx-auto px-6 py-14 sm:py-20">
      {user.role === "student" && (
        <OnboardingTour
          steps={learnerSteps(t)}
          storageKey="lumen.onboarding.learner.dismissed"
        />
      )}
      <header className="mb-12 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("dashboard.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("dashboard.welcome", { name: firstName })}
        </h1>
        <p className="font-body text-sm text-muted-foreground">{t("dashboard.subtitle")}</p>
      </header>

      <section className="mb-14">
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            {t("dashboard.inProgress")}
          </h2>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {inProgress.length}
          </span>
        </div>
        {inProgress.length === 0 ? (
          <div className="surface px-5 py-10 text-center">
            <p className="font-body text-sm text-muted-foreground">
              {t("dashboard.empty.enrollments")}{" "}
              <Link
                href="/courses"
                className="text-foreground underline-offset-4 transition-colors duration-[160ms] hover:underline"
              >
                {t("dashboard.empty.browse")}
              </Link>
              .
            </p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {inProgress.map((e) => (
              <article
                key={e.id}
                className="surface flex flex-col gap-3 p-5 transition-colors duration-[160ms] hover:border-foreground/30"
              >
                <h3 className="font-display text-base leading-tight tracking-tight">
                  <Link
                    href={`/courses/${e.course.slug}`}
                    className="transition-colors duration-[160ms] hover:text-muted-foreground"
                  >
                    {e.course.title}
                  </Link>
                </h3>
                <Progress value={e.progress_pct} />
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {t("dashboard.percentComplete", { pct: e.progress_pct.toFixed(0) })}
                  </span>
                  <Link
                    href={`/learn/${e.course.slug}`}
                    className="inline-flex items-center gap-1 font-body text-sm text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                  >
                    {t("dashboard.continue")} <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            {t("dashboard.completed")}
          </h2>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {done.length}
          </span>
        </div>
        {done.length === 0 ? (
          <div className="border-t border-border px-1 py-8">
            <p className="font-body text-sm text-muted-foreground">
              {t("dashboard.empty.completed")}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {done.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between gap-3 py-3 transition-colors duration-[160ms] hover:bg-muted/30"
              >
                <Link
                  href={`/courses/${e.course.slug}`}
                  className="font-body text-sm text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                >
                  {e.course.title}
                </Link>
                {e.certificate_id && (
                  <div className="flex items-center gap-4">
                    {/* Phase E5: the OB3 / W3C VC link sits next to
                        the PDF download. A learner who wants to keep
                        the credential in a wallet or paste it into a
                        verifier opens the JSON-LD; the PDF stays as
                        the human-facing fallback. */}
                    <a
                      href={`/api/v1/credentials/${e.certificate_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
                    >
                      {t("dashboard.openBadge")}
                    </a>
                    <a
                      href={`/api/v1/certificates/${e.course.id}.pdf`}
                      className="inline-flex items-center gap-1 font-body text-sm text-primary transition-colors duration-[160ms] hover:text-primary/80"
                    >
                      {t("dashboard.certificate")}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </a>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
