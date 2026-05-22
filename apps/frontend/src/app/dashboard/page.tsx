"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Award, BookOpen, ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

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
    <div className="container mx-auto px-6 py-20 sm:py-24">
      <header className="mb-16 flex flex-col gap-3">
        <p className="font-body text-sm font-medium uppercase tracking-[0.18em] text-primary">
          {t("dashboard.cartouche")}
        </p>
        <h1 className="font-display text-5xl leading-[1.05] tracking-tight sm:text-6xl">
          {t("dashboard.welcome", { name: firstName })}
        </h1>
        <p className="font-body text-lg text-muted-foreground">{t("dashboard.subtitle")}</p>
      </header>

      <section className="mb-16">
        <h2 className="mb-6 inline-flex items-center gap-2.5 font-display text-3xl leading-tight tracking-tight">
          <BookOpen className="h-5 w-5 text-primary" />
          {t("dashboard.inProgress")}
        </h2>
        {inProgress.length === 0 ? (
          <Card className="surface">
            <CardContent className="py-14 text-center">
              <p className="font-body text-muted-foreground">
                {t("dashboard.empty.enrollments")}{" "}
                <Link
                  href="/courses"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  {t("dashboard.empty.browse")}
                </Link>
                .
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {inProgress.map((e) => (
              <Card
                key={e.id}
                className="surface transition-shadow duration-500 hover:shadow-[0_12px_32px_-12px_hsl(0_0%_0%/0.12)]"
              >
                <CardHeader>
                  <CardTitle className="font-display text-2xl leading-tight">
                    <Link
                      href={`/courses/${e.course.slug}`}
                      className="transition-colors hover:text-primary"
                    >
                      {e.course.title}
                    </Link>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Progress value={e.progress_pct} />
                  <p className="font-body text-sm text-muted-foreground">
                    {t("dashboard.percentComplete", { pct: e.progress_pct.toFixed(0) })}
                  </p>
                  <Link
                    href={`/learn/${e.course.slug}`}
                    className="inline-flex items-center gap-1 font-body text-sm font-medium text-primary hover:underline"
                  >
                    {t("dashboard.continue")} <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-6 inline-flex items-center gap-2.5 font-display text-3xl leading-tight tracking-tight">
          <Award className="h-5 w-5 text-primary" />
          {t("dashboard.completed")}
        </h2>
        {done.length === 0 ? (
          <div className="surface px-6 py-12 text-center">
            <p className="font-body italic text-muted-foreground">
              {t("dashboard.empty.completed")}
            </p>
          </div>
        ) : (
          <ul className="space-y-2 text-sm">
            {done.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between rounded-md border border-border/60 bg-card p-4 transition-colors hover:border-primary/40"
              >
                <span className="font-body">{e.course.title}</span>
                {e.certificate_id && (
                  <a
                    href={`/api/v1/certificates/${e.course.id}.pdf`}
                    className="inline-flex items-center gap-1 font-body text-sm font-medium text-primary underline-offset-4 hover:underline"
                  >
                    {t("dashboard.certificate")}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
